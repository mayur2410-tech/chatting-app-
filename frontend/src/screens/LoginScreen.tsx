import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";
import { ArrowLeftRight, CalendarDays, Eye, EyeOff, Plane, PlaneLanding, PlaneTakeoff, ShieldCheck, Users } from "lucide-react";
import { AppLogo } from "../components/AppLogo";
import { SkyScene } from "../components/landing/SkyScene";
import { PlaneSpinner } from "../components/PlaneLoader";
import { APP_NAME } from "../config";

interface LoginScreenProps {
  /** Resolves to an error message to display, or null on success. */
  onSubmit: (username: string, password: string) => Promise<string | null>;
  /** Informational message, e.g. after a session expired. */
  notice?: string | null;
}

type RouteFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  id: string;
  label: string;
  hint: string;
  icon: ReactNode;
  trailing?: ReactNode;
};

/** A booking-style field: big "From"/"To" label, a hint, and the input. */
function RouteField({ id, label, hint, icon, trailing, ...input }: RouteFieldProps) {
  return (
    <label
      htmlFor={id}
      className="group relative flex flex-1 items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 transition focus-within:border-sky-500 focus-within:ring-4 focus-within:ring-sky-500/15 dark:border-slate-700 dark:bg-slate-900"
    >
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-400">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          {label} <span className="font-normal normal-case tracking-normal text-slate-400">· {hint}</span>
        </span>
        <input
          id={id}
          className="w-full bg-transparent text-lg font-semibold text-slate-900 outline-none placeholder:font-normal placeholder:text-slate-300 dark:text-slate-100 dark:placeholder:text-slate-600"
          {...input}
        />
      </span>
      {trailing}
    </label>
  );
}

function TripChip({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-slate-100/80 px-3 py-2 dark:bg-slate-800/70">
      <span className="text-sky-600 dark:text-sky-400">{icon}</span>
      <span className="leading-tight">
        <span className="block text-[10px] font-semibold uppercase tracking-widest text-slate-400">{label}</span>
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{value}</span>
      </span>
    </div>
  );
}

const ROUTES = [
  { city: "Paris", code: "CDG", emoji: "🗼", tint: "from-rose-400 to-orange-300" },
  { city: "Tokyo", code: "HND", emoji: "🗻", tint: "from-sky-500 to-indigo-400" },
  { city: "Bali", code: "DPS", emoji: "🏝️", tint: "from-emerald-400 to-teal-300" },
  { city: "Dubai", code: "DXB", emoji: "🏙️", tint: "from-amber-400 to-yellow-300" },
];

/**
 * Sign-in, presented as a flight-booking landing page: "From" is the username and "To" is the
 * password. Everything else on the page is decoration.
 */
export function LoginScreen({ onSubmit, notice }: LoginScreenProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (!username.trim() || !password) {
      setError("Incorrect username or password.");
      return;
    }
    setBusy(true);
    const submitted = password;
    // Don't keep the password in component state longer than the request needs.
    setPassword("");
    const message = await onSubmit(username.trim(), submitted);
    setBusy(false);
    if (message) setError(message);
  }

  return (
    <div className="app-shell overflow-y-auto bg-sky-50 dark:bg-slate-950">
      {/* Top bar */}
      <header className="safe-top sticky top-0 z-20 border-b border-white/30 bg-sky-950/85 text-white backdrop-blur dark:border-white/10">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3">
          <AppLogo size={34} />
          <div className="leading-tight">
            <p className="text-base font-bold tracking-tight">{APP_NAME} Airways</p>
            <p className="text-[10px] uppercase tracking-[0.25em] text-sky-300">Private flights for two</p>
          </div>
          <span className="ml-auto hidden items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs text-sky-100 sm:flex">
            <ShieldCheck className="size-3.5" aria-hidden="true" />
            Members only
          </span>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden bg-gradient-to-b from-sky-500 via-sky-300 to-sky-50 dark:from-[#0b1d33] dark:via-[#0a1628] dark:to-slate-950">
        <SkyScene />
        <div className="relative mx-auto max-w-5xl px-4 pb-10 pt-40 sm:pt-48">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-white/90 drop-shadow">Your private route</p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight text-white drop-shadow-md sm:text-6xl">
            Where to next?
          </h1>
          <p className="mt-2 max-w-md text-sm text-white/90 drop-shadow sm:text-base">
            Two seats, one cabin, no other passengers. Enter your route to board.
          </p>

          {/* Booking card = sign-in form */}
          <form
            onSubmit={handleSubmit}
            noValidate
            className="animate-fade-up mt-6 rounded-3xl bg-white/95 p-4 shadow-2xl shadow-sky-950/20 ring-1 ring-sky-900/5 backdrop-blur sm:p-6 dark:bg-slate-900/95 dark:ring-white/10"
            aria-label="Sign in"
          >
            <div className="mb-4 flex gap-2 text-xs font-semibold" aria-hidden="true">
              <span className="rounded-full bg-sky-600 px-3 py-1 text-white">One way</span>
              <span className="rounded-full px-3 py-1 text-slate-400">Private charter</span>
            </div>

            <div className="relative flex flex-col gap-2 md:flex-row md:items-stretch">
              <RouteField
                id="username"
                label="From"
                hint="your username"
                icon={<PlaneTakeoff className="size-5" aria-hidden="true" />}
                placeholder="Username"
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                maxLength={64}
              />
              {/* Swap badge, like real booking sites (decorative) */}
              <span
                className="absolute left-1/2 top-1/2 z-10 flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-4 border-white bg-sky-600 text-white shadow-md dark:border-slate-900"
                aria-hidden="true"
              >
                <ArrowLeftRight className="size-4 rotate-90 md:rotate-0" />
              </span>
              <RouteField
                id="password"
                label="To"
                hint="your password"
                icon={<PlaneLanding className="size-5" aria-hidden="true" />}
                type={showPassword ? "text" : "password"}
                placeholder="Password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={256}
                trailing={
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
                  </button>
                }
              />
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2" aria-hidden="true">
              <TripChip icon={<CalendarDays className="size-4" />} label="Departure" value="Today" />
              <TripChip icon={<Users className="size-4" />} label="Passengers" value="2" />
              <TripChip icon={<Plane className="size-4" />} label="Class" value="Private" />
            </div>

            <div className="mt-3 min-h-5" aria-live="polite">
              {error ? (
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              ) : (
                notice && <p className="text-sm text-sky-700 dark:text-sky-300">{notice}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={busy}
              aria-label="Sign in"
              className="mt-2 inline-flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-sky-600 to-sky-500 text-base font-bold text-white shadow-lg shadow-sky-600/30 transition hover:from-sky-500 hover:to-sky-400 active:scale-[0.99] disabled:opacity-80"
            >
              {busy ? (
                <>
                  <PlaneSpinner className="size-6" />
                  Taking off…
                </>
              ) : (
                <>
                  <PlaneTakeoff className="size-5" aria-hidden="true" />
                  Take off
                </>
              )}
            </button>
          </form>
        </div>
      </section>

      {/* Popular routes (decorative) */}
      <section className="mx-auto max-w-5xl px-4 pb-10" aria-hidden="true">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">
          Popular routes
        </h2>
        <div className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2">
          {ROUTES.map((r) => (
            <div
              key={r.code}
              className={`relative h-32 w-40 shrink-0 snap-start overflow-hidden rounded-2xl bg-gradient-to-br ${r.tint} p-3 text-white shadow-md`}
            >
              <span className="absolute -bottom-2 -right-1 text-6xl opacity-90">{r.emoji}</span>
              <p className="font-mono text-xs font-semibold tracking-widest opacity-90">DUO ✈ {r.code}</p>
              <p className="mt-1 text-lg font-bold">{r.city}</p>
            </div>
          ))}
        </div>
        <p className="mt-6 text-center text-xs text-slate-400 dark:text-slate-500">
          © {APP_NAME} Airways · Boarding for 2 passengers only
        </p>
      </section>
    </div>
  );
}
