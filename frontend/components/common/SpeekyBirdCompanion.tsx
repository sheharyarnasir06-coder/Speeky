"use client";

import Image from "next/image";
import { usePathname } from "next/navigation";
import * as React from "react";

export function SpeekyBirdCompanion() {
  const pathname = usePathname();
  const [position, setPosition] = React.useState({ x: 28, y: 32 });
  const [target, setTarget] = React.useState({ x: 28, y: 32 });

  React.useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      const nextX = Math.min(92, Math.max(8, (event.clientX / window.innerWidth) * 100));
      const nextY = Math.min(88, Math.max(12, (event.clientY / window.innerHeight) * 100));
      setTarget({ x: nextX, y: nextY });
    }

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    return () => window.removeEventListener("pointermove", handlePointerMove);
  }, []);

  React.useEffect(() => {
    let frame = 0;

    function tick() {
      setPosition((current) => ({
        x: current.x + (target.x - current.x) * 0.045,
        y: current.y + (target.y - current.y) * 0.045,
      }));
      frame = window.requestAnimationFrame(tick);
    }

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [target]);

  if (pathname === "/") return null;

  return (
    <div
      className="pointer-events-none fixed z-[60] hidden h-12 w-12 -translate-x-1/2 -translate-y-1/2 select-none opacity-80 transition-opacity duration-300 motion-reduce:hidden lg:block"
      style={{
        left: `${position.x}%`,
        top: `${position.y}%`,
      }}
      aria-hidden="true"
    >
      <div className="animate-[speeky-bird-float_2.4s_ease-in-out_infinite] rounded-full bg-surface/70 p-2 shadow-lg shadow-primary/10 backdrop-blur-sm">
        <Image
          src="/logo-icon.png"
          alt=""
          width={32}
          height={32}
          className="h-8 w-8 object-contain"
          priority={false}
        />
      </div>
    </div>
  );
}
