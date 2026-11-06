/** Top-down plane silhouette, pointing up (same artwork as the logo). */
export const PLANE_PATH =
  "M32 6c2 0 3 2 3 4v14l21 12v5l-21-6v13l6 5v4l-9-2.5-9 2.5v-4l6-5V35L8 41v-5l21-12V10c0-2 1-4 3-4z";

interface PlaneLoaderProps {
  label?: string;
  size?: number;
  className?: string;
}

/**
 * A plane circling a dashed flight path around a small globe. Used wherever the app waits:
 * start-up, loading messages, signing in.
 */
export function PlaneLoader({ label, size = 72, className = "" }: PlaneLoaderProps) {
  return (
    <div className={`flex flex-col items-center gap-3 ${className}`} role="status" aria-live="polite">
      <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
        {/* Globe */}
        <circle cx="50" cy="50" r="17" className="fill-sky-100 dark:fill-sky-950" />
        <path
          d="M33 50h34M50 33c-6 5-6 29 0 34M50 33c6 5 6 29 0 34"
          fill="none"
          strokeWidth="1.5"
          className="stroke-sky-400/70"
        />
        <circle cx="50" cy="50" r="17" fill="none" strokeWidth="1.5" className="stroke-sky-400/70" />
        {/* Flight path */}
        <circle cx="50" cy="50" r="36" fill="none" strokeWidth="2" className="flight-path stroke-sky-400/60" />
        {/* Orbiting plane (points along the direction of travel) */}
        <g className="animate-orbit">
          <g transform="translate(50 14) rotate(90) scale(0.32) translate(-32 -32)">
            <path d={PLANE_PATH} className="fill-sky-600 dark:fill-sky-400" />
          </g>
        </g>
      </svg>
      {label && <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</p>}
      {!label && <span className="sr-only">Loading</span>}
    </div>
  );
}

/** Small inline version for buttons and compact spots. */
export function PlaneSpinner({ className = "size-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true">
      <circle cx="50" cy="50" r="36" fill="none" strokeWidth="8" className="flight-path stroke-current opacity-40" />
      <g className="animate-orbit">
        <g transform="translate(50 14) rotate(90) scale(0.55) translate(-32 -32)">
          <path d={PLANE_PATH} className="fill-current" />
        </g>
      </g>
    </svg>
  );
}
