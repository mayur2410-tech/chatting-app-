import type { ButtonHTMLAttributes } from "react";
import { PlaneSpinner } from "./PlaneLoader";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
  loading?: boolean;
};

const BUTTON_STYLES = {
  primary: "bg-sky-600 text-white shadow-sm shadow-sky-900/20 hover:bg-sky-500 dark:bg-sky-500 dark:hover:bg-sky-400",
  ghost: "text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-800",
  danger: "bg-red-600 text-white hover:bg-red-500",
} as const;

export function Button({ variant = "primary", loading, disabled, className = "", children, ...rest }: ButtonProps) {
  return (
    <button
      className={`inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl text-sm font-semibold transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500 ${BUTTON_STYLES[variant]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <PlaneSpinner className="size-5" />}
      {children}
    </button>
  );
}

export function IconButton({ className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`inline-flex size-10 shrink-0 items-center justify-center rounded-full transition active:scale-95 disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-sky-400 ${className}`}
      {...rest}
    />
  );
}
