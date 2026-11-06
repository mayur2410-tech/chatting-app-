interface AppLogoProps {
  size?: number;
  className?: string;
}

/** Duo's mark: a plane on a sky-blue tile (same artwork as the favicon). */
export function AppLogo({ size = 48, className }: AppLogoProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className={className}>
      <rect width="64" height="64" rx="16" className="fill-sky-600 dark:fill-sky-500" />
      <path
        transform="rotate(45 32 32)"
        className="fill-white"
        d="M32 6c2 0 3 2 3 4v14l21 12v5l-21-6v13l6 5v4l-9-2.5-9 2.5v-4l6-5V35L8 41v-5l21-12V10c0-2 1-4 3-4z"
      />
    </svg>
  );
}
