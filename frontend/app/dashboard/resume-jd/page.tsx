"use client";

import * as React from "react";
import { CheckCircle2, FileText, TriangleAlert, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  checkMismatch,
  listResumes,
  submitJd,
  uploadResume,
  type JDIntakeResult,
  type MismatchCheckResult,
  type ResumeSummary,
  type ResumeUploadResult,
} from "@/lib/resumeJd";

interface JdEntry {
  jd_id: string;
  label: string;
}

export default function ResumeJdPage() {
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const [resumes, setResumes] = React.useState<ResumeSummary[]>([]);
  const [isUploading, setIsUploading] = React.useState(false);
  const [uploadResult, setUploadResult] = React.useState<ResumeUploadResult | null>(null);
  const [uploadError, setUploadError] = React.useState<string | null>(null);

  const [jdText, setJdText] = React.useState("");
  const [jds, setJds] = React.useState<JdEntry[]>([]);
  const [isSubmittingJd, setIsSubmittingJd] = React.useState(false);
  const [jdResult, setJdResult] = React.useState<JDIntakeResult | null>(null);
  const [jdError, setJdError] = React.useState<string | null>(null);

  const [selectedResumeId, setSelectedResumeId] = React.useState<string | null>(null);
  const [selectedJdId, setSelectedJdId] = React.useState<string | null>(null);
  const [isChecking, setIsChecking] = React.useState(false);
  const [mismatchResult, setMismatchResult] = React.useState<MismatchCheckResult | null>(null);
  const [mismatchError, setMismatchError] = React.useState<string | null>(null);

  React.useEffect(() => {
    listResumes()
      .then(setResumes)
      .catch(() => {});
  }, []);

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setUploadError(null);
    setIsUploading(true);
    try {
      const result = await uploadResume(file);
      setUploadResult(result);
      if (result.parse_status === "success") {
        setResumes((prev) => [
          { resume_id: result.resume_id, filename: result.filename, parse_status: result.parse_status, uploaded_at: result.uploaded_at, last_modified_label: result.last_modified_label },
          ...prev,
        ]);
        setSelectedResumeId(result.resume_id);
      }
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleSubmitJd() {
    if (jdText.trim().length < 10) {
      setJdError("Paste the full job description.");
      return;
    }
    setJdError(null);
    setIsSubmittingJd(true);
    try {
      const result = await submitJd(jdText);
      setJdResult(result);
      setJds((prev) => [{ jd_id: result.jd_id, label: `JD ${prev.length + 1} — ${result.cleaned_word_count} words` }, ...prev]);
      setSelectedJdId(result.jd_id);
    } catch (err) {
      setJdError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmittingJd(false);
    }
  }

  async function handleCheckMismatch() {
    if (!selectedResumeId || !selectedJdId) return;
    setMismatchError(null);
    setIsChecking(true);
    try {
      const result = await checkMismatch(selectedResumeId, selectedJdId);
      setMismatchResult(result);
    } catch (err) {
      setMismatchError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsChecking(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="font-serif text-h1 font-semibold text-foreground">
          Resume &amp; Job Description
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Upload your resume and a job description so Interview Coach can tailor questions to you.
        </p>
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <h2 className="font-serif text-lg font-semibold text-foreground">Resume</h2>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          className="hidden"
          onChange={handleUpload}
        />
        <Button
          size="sm"
          variant="outline"
          className="mt-3"
          loading={isUploading}
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload className="h-4 w-4" aria-hidden="true" />
          Upload Resume (PDF, DOCX, or TXT)
        </Button>

        {uploadError ? <p className="mt-3 text-sm text-danger">{uploadError}</p> : null}
        {uploadResult ? (
          <div
            className={cn(
              "mt-3 flex items-start gap-2.5 rounded-xl px-4 py-3 text-sm",
              uploadResult.parse_status === "success"
                ? "bg-success/10 text-success"
                : "bg-warning/10 text-foreground",
            )}
          >
            {uploadResult.parse_status === "success" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            ) : (
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            )}
            {uploadResult.warning ?? `Uploaded — ${uploadResult.extracted_word_count} words extracted.`}
          </div>
        ) : null}

        {resumes.length > 0 ? (
          <div className="mt-4 flex flex-col gap-2">
            {resumes.map((r) => (
              <button
                key={r.resume_id}
                type="button"
                onClick={() => setSelectedResumeId(r.resume_id)}
                className={cn(
                  "flex items-center gap-2 rounded-xl border p-3 text-left text-sm transition-colors",
                  selectedResumeId === r.resume_id
                    ? "border-primary bg-secondary"
                    : "border-border hover:bg-surface",
                )}
              >
                <FileText className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                <span className="text-foreground">{r.last_modified_label}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <h2 className="font-serif text-lg font-semibold text-foreground">Job Description</h2>
        <div className="mt-3">
          <Textarea
            label="Paste the job description"
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            rows={6}
          />
        </div>
        {jdError ? <p className="mt-2 text-sm text-danger">{jdError}</p> : null}
        {jdResult?.warning ? (
          <p className="mt-2 text-sm text-warning">{jdResult.warning}</p>
        ) : null}
        <Button size="sm" className="mt-3" loading={isSubmittingJd} onClick={handleSubmitJd}>
          Save Job Description
        </Button>

        {jds.length > 0 ? (
          <div className="mt-4 flex flex-col gap-2">
            {jds.map((jd) => (
              <button
                key={jd.jd_id}
                type="button"
                onClick={() => setSelectedJdId(jd.jd_id)}
                className={cn(
                  "flex items-center gap-2 rounded-xl border p-3 text-left text-sm transition-colors",
                  selectedJdId === jd.jd_id ? "border-primary bg-secondary" : "border-border hover:bg-surface",
                )}
              >
                <FileText className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                <span className="text-foreground">{jd.label}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <h2 className="font-serif text-lg font-semibold text-foreground">Mismatch Check</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Compare your resume against the job description&apos;s key skills.
        </p>
        <Button
          size="sm"
          className="mt-3"
          loading={isChecking}
          disabled={!selectedResumeId || !selectedJdId}
          onClick={handleCheckMismatch}
        >
          Run Check
        </Button>
        {mismatchError ? <p className="mt-3 text-sm text-danger">{mismatchError}</p> : null}
        {mismatchResult ? (
          <div className="mt-4 flex flex-col gap-3">
            <div
              className={cn(
                "rounded-xl px-4 py-3 text-sm",
                mismatchResult.mismatch_detected ? "bg-warning/10 text-foreground" : "bg-success/10 text-success",
              )}
            >
              {mismatchResult.note} ({Math.round(mismatchResult.overlap_score * 100)}% overlap)
            </div>
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <p className="font-medium text-foreground">Your skills</p>
                <p className="mt-1 text-muted-foreground">
                  {mismatchResult.resume_keywords_found.join(", ") || "None detected"}
                </p>
              </div>
              <div>
                <p className="font-medium text-foreground">JD skills</p>
                <p className="mt-1 text-muted-foreground">
                  {mismatchResult.jd_keywords_found.join(", ") || "None detected"}
                </p>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <Button href="/dashboard/interview-coach" variant="outline" size="lg" className="self-center">
        Go to Interview Coach
      </Button>
    </div>
  );
}
