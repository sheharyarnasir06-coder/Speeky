"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "react-toastify";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { login } from "@/lib/auth";
import { useAuth } from "@/contexts/AuthContext";
import { EMAIL_DOMAIN_ERROR, isAllowedEmailDomain } from "@/lib/validation";

interface LoginValues {
  email: string;
  password: string;
}

interface LoginFormProps {
  onSubmit?: (values: LoginValues) => Promise<void> | void;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function validate(values: LoginValues) {
  const errors: Partial<Record<keyof LoginValues, string>> = {};

  if (!values.email.trim()) {
    errors.email = "Email is required.";
  } else if (!EMAIL_PATTERN.test(values.email.trim())) {
    errors.email = "Enter a valid email address.";
  } else if (!isAllowedEmailDomain(values.email)) {
    errors.email = EMAIL_DOMAIN_ERROR;
  }

  if (!values.password) {
    errors.password = "Password is required.";
  }

  return errors;
}

/**
 * Login form — email + password only. Validates inline as soon as a
 * field has been touched, not just on submit. Ready to wire up: pass
 * an `onSubmit` handler that calls the real auth API.
 */
export function LoginForm({ onSubmit }: LoginFormProps) {
  const router = useRouter();
  const { setUser } = useAuth();
  const [values, setValues] = React.useState<LoginValues>({
    email: "",
    password: "",
  });
  const [touched, setTouched] = React.useState<
    Partial<Record<keyof LoginValues, boolean>>
  >({});
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const errors = validate(values);

  function handleChange(field: keyof LoginValues, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  function handleBlur(field: keyof LoginValues) {
    setTouched((prev) => ({ ...prev, [field]: true }));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched({ email: true, password: true });
    setFormError(null);

    const currentErrors = validate(values);
    if (Object.keys(currentErrors).length > 0) {
      return;
    }

    try {
      setIsSubmitting(true);
      if (onSubmit) {
        await onSubmit(values);
      } else {
        const { user } = await login({
          email: values.email.trim(),
          password: values.password,
        });

        toast.success(`Login successful for ${user.name.split(" ")[0]}!`);
        setUser(user);
        router.push("/dashboard");
      }
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Something went wrong. Please try again.";
      setFormError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
      <Input
        label="Email"
        type="email"
        autoComplete="email"
        value={values.email}
        onChange={(event) => handleChange("email", event.target.value)}
        onBlur={() => handleBlur("email")}
        error={touched.email ? errors.email : undefined}
      />
      <Input
        label="Password"
        type="password"
        autoComplete="current-password"
        value={values.password}
        onChange={(event) => handleChange("password", event.target.value)}
        onBlur={() => handleBlur("password")}
        error={touched.password ? errors.password : undefined}
      />

      <Link
        href="/forgot-password"
        className="-mt-3 self-end text-sm font-medium text-primary hover:text-primary-hover"
      >
        Forgot password?
      </Link>

      {formError ? <p className="text-sm text-danger">{formError}</p> : null}

      <Button type="submit" size="lg" loading={isSubmitting} className="mt-2">
        Log In
      </Button>
    </form>
  );
}
