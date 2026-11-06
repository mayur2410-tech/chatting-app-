import { PLANE_PATH } from "../PlaneLoader";

/** A fluffy cloud built from overlapping arcs. */
function Cloud({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg viewBox="0 0 120 60" className={className} style={style} aria-hidden="true">
      <path
        d="M22 52a18 18 0 0 1-2-35.8A24 24 0 0 1 64 8a20 20 0 0 1 34 12 16 16 0 0 1 2 32z"
        className="fill-white/90 dark:fill-slate-200/10"
      />
    </svg>
  );
}

/**
 * Decorative hero background: a sky gradient with sun (moon in dark mode), drifting clouds and
 * an airliner cruising with a contrail. Pure SVG/CSS, so no external images are loaded.
 */
export function SkyScene() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      {/* Sun / moon */}
      <div className="absolute left-[52%] top-8 size-16 rounded-full bg-gradient-to-br from-amber-200 to-amber-400 opacity-90 blur-[1px] shadow-[0_0_80px_30px] shadow-amber-200/60 dark:from-slate-200 dark:to-slate-400 dark:opacity-70 dark:shadow-slate-300/20 sm:size-20" />

      {/* Distant clouds (slow) */}
      <Cloud className="animate-drift absolute top-[14%] w-40 opacity-70" style={{ animationDuration: "70s", animationDelay: "-20s" }} />
      <Cloud className="animate-drift absolute top-[38%] w-28 opacity-60" style={{ animationDuration: "85s", animationDelay: "-55s" }} />

      {/* The plane, cruising up and to the right with a contrail */}
      <div className="absolute right-[2%] top-[6%] w-[min(58vw,380px)] sm:right-[6%]">
        <div className="animate-cruise">
          <svg viewBox="0 0 400 200" className="w-full drop-shadow-xl" aria-hidden="true">
            <defs>
              <linearGradient id="trail" x1="0" x2="1">
                <stop offset="0" stopColor="white" stopOpacity="0" />
                <stop offset="1" stopColor="white" stopOpacity="0.9" />
              </linearGradient>
            </defs>
            <path d="M10 180 L250 70" stroke="url(#trail)" strokeWidth="5" strokeLinecap="round" className="animate-contrail" />
            <path d="M20 192 L262 82" stroke="url(#trail)" strokeWidth="5" strokeLinecap="round" className="animate-contrail" />
            <g transform="translate(300 60) rotate(65) scale(2.2) translate(-32 -32)">
              <path d={PLANE_PATH} className="fill-white" />
              <path d="M32 6c2 0 3 2 3 4v14H29V10c0-2 1-4 3-4z" className="fill-sky-200" />
            </g>
          </svg>
        </div>
      </div>

      {/* Near clouds (faster, in front of the plane) */}
      <Cloud className="animate-drift absolute top-[28%] w-56" style={{ animationDuration: "45s", animationDelay: "-10s" }} />
      <Cloud className="animate-drift absolute top-[52%] w-44 opacity-90" style={{ animationDuration: "55s", animationDelay: "-35s" }} />

      {/* Soft horizon glow */}
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-sky-50 to-transparent dark:from-slate-950" />
    </div>
  );
}
