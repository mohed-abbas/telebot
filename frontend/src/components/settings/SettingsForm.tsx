// frontend/src/components/settings/SettingsForm.tsx — the rhf+zod settings form (SUX-02/03/04).
//
// The first react-hook-form form in the repo. Field markup mirrors LoginView (Label + Input +
// role="alert" inline error), but the rhf+zod wiring is new:
//   • resolver = zodResolver(makeSettingsSchema(values.max_lot_size)) — the per-account cap factory
//     (SUX-03, defense-in-depth; the server re-validates on confirm — T-11-12).
//   • defaultValues = the BARE server values (risk_value is a float, not a _display string).
//
// Mode-aware (the load-bearing distinction):
//   • risk_mode is a shadcn select (Percent of balance / Fixed lot size). Switching mode re-labels
//     risk_value (percent → "Per-trade risk (%)" / fixed_lot → "Total lot size") and re-computes the
//     inline footgun.
//   • The inline footgun (amber AlertTriangle — NOT destructive red, NOT cyan primary) renders live
//     off footgun(mode, risk_value, max_stages) via watch(). fixed_lot does NOT multiply (Pitfall 6).
//
// max_open_trades is editable: it lives on the accounts row server-side but shares the
// validate → confirm → audit → revert path. It must be ≥ max_stages (entries above the cap
// can never open), enforced by the zod schema and, authoritatively, by the server.
//
// "Review changes" is the primary CTA: it opens the validate→confirm-diff flow via onReview(values).
// It does NOT persist — that is the confirm step (ConfirmDiffDialog).

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertTriangle } from "lucide-react";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DEFAULT_ENTRY_TP, entryTps, withEntryTp } from "@/lib/entryTps";
import { footgun } from "@/lib/footgun";
import { makeSettingsSchema } from "@/lib/settingsSchema";

// The EDITABLE/submitted field set (max_lot_size is NOT here — read-only).
export interface SettingsFormValues {
  risk_mode: "percent" | "fixed_lot";
  risk_value: number;
  max_stages: number;
  default_sl_pips: number;
  max_daily_trades: number;
  max_open_trades: number;
  // Provider TP number per entry in fill order ([0] = entry 1). Sent as exactly max_stages
  // values; the server drops trailing defaults, so "TP2 everywhere" is stored as [].
  stage_tp_map: number[];
}

const TP_CHOICES = [1, 2, 3, 4, 5] as const;

/** The full BARE server `values` dict (the GET response) — drives defaults + read-only fields. */
export interface SettingsServerValues extends SettingsFormValues {
  // Per-account cap (feeds the zod fixed_lot branch). Read-only — not editable, not submitted.
  max_lot_size: number;
  // The TP an unmapped entry uses (the parser's default target). Read-only.
  default_entry_tp?: number;
}

export interface SettingsFormProps {
  /** The bare server values from GET /api/v2/settings/{account}. */
  values: SettingsServerValues;
  /** Opens the two-step validate flow with the typed values. Does NOT persist. */
  onReview: (values: SettingsFormValues) => void;
}

export function SettingsForm({ values, onReview }: SettingsFormProps) {
  const defaultTp = values.default_entry_tp ?? DEFAULT_ENTRY_TP;
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<SettingsFormValues>({
    // Per-account cap factory (SUX-03) — max_lot_size read from the GET response (Pitfall: per-account).
    resolver: zodResolver(makeSettingsSchema(values.max_lot_size)),
    defaultValues: {
      risk_mode: values.risk_mode,
      risk_value: values.risk_value,
      max_stages: values.max_stages,
      default_sl_pips: values.default_sl_pips,
      max_daily_trades: values.max_daily_trades,
      max_open_trades: values.max_open_trades,
      stage_tp_map: entryTps(values.stage_tp_map, values.max_stages, defaultTp),
    },
  });

  // Live mode-aware footgun inputs — re-render as these change (watch returns the current value).
  const mode = watch("risk_mode");
  const riskValue = watch("risk_value");
  const maxStages = watch("max_stages");
  const maxOpenTrades = watch("max_open_trades");
  const stageTpMap = watch("stage_tp_map");
  // Always one selector per entry, following Maximum entries as it changes.
  const tpPerEntry = entryTps(stageTpMap, maxStages, defaultTp);

  function setEntryTp(index: number, tp: number) {
    setValue("stage_tp_map", withEntryTp(stageTpMap ?? [], index, tp, defaultTp), {
      shouldValidate: true,
    });
  }

  // Submit exactly one TP per entry (drops selections left over from a larger entry count).
  const submit = handleSubmit((v) =>
    onReview({ ...v, stage_tp_map: entryTps(v.stage_tp_map, v.max_stages, defaultTp) }),
  );

  const riskValueLabel =
    mode === "percent" ? "Per-trade risk (%)" : "Total lot size";
  const riskValueHelp =
    mode === "percent"
      ? `Percent of balance risked per trade. Max: 5.0%.`
      : `Total lots across all entries for this signal (not per trade). Max: ${values.max_lot_size}.`;

  // The inline footgun copy (mode-aware — percent multiplies; fixed_lot does NOT, Pitfall 6).
  // Guard against NaN-while-typing so the warning never renders garbage.
  const footgunText =
    Number.isFinite(riskValue) && Number.isFinite(maxStages) && Number.isFinite(maxOpenTrades)
      ? footgun(mode, riskValue, maxStages, maxOpenTrades)
      : null;

  return (
    <TooltipProvider>
      <form
        onSubmit={submit}
        className="flex flex-col gap-5"
        aria-label="Account settings"
      >
        {/* risk_mode — shadcn select. Switching re-labels risk_value + recomputes the footgun. */}
        <div className="flex flex-col gap-2">
          <FieldLabel
            htmlFor="risk_mode"
            label="Risk calculation"
            help="How lot size is determined: 'Percent of balance' calculates from equity; 'Fixed lot' uses an exact lot size."
          />
          <Select
            value={mode}
            onValueChange={(v) =>
              setValue("risk_mode", v as SettingsFormValues["risk_mode"], {
                shouldValidate: true,
              })
            }
          >
            <SelectTrigger id="risk_mode" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="percent">Percent of balance</SelectItem>
              <SelectItem value="fixed_lot">Fixed lot size</SelectItem>
            </SelectContent>
          </Select>
          {errors.risk_mode && (
            <p role="alert" className="text-sm text-destructive">
              {errors.risk_mode.message}
            </p>
          )}
        </div>

        {/* risk_value — mode-aware label + help. */}
        <NumberField
          id="risk_value"
          label={riskValueLabel}
          help={riskValueHelp}
          step="any"
          error={errors.risk_value?.message}
          register={register("risk_value", { valueAsNumber: true })}
        />

        {/* Inline footgun — amber AlertTriangle (NOT destructive red, NOT cyan). Lives right under
            the two fields that drive it so the operator sees the compounded exposure while editing. */}
        {footgunText && (
          <div
            role="note"
            className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-400"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{footgunText}</span>
          </div>
        )}

        <NumberField
          id="max_stages"
          label="Maximum entries per signal"
          help="How many positions one signal may open (1–10)."
          step="1"
          error={errors.max_stages?.message}
          register={register("max_stages", { valueAsNumber: true })}
        />

        {/* Per-entry take-profit — one TP selector per entry, in fill order. */}
        <div className="flex flex-col gap-2">
          <FieldLabel
            htmlFor="stage_tp_1"
            label="Take-profit per entry"
            help="Which of the signal's TPs each entry closes at, in fill order (entry 1 = the first fill, the last entry = the deepest). Every entry keeps the signal's SL. If a signal has fewer TPs, its last TP is used."
          />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {tpPerEntry.map((tp, i) => (
              <div key={i} className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Entry {i + 1}</span>
                <Select
                  value={String(tp)}
                  onValueChange={(v) => setEntryTp(i, Number(v))}
                >
                  <SelectTrigger
                    id={`stage_tp_${i + 1}`}
                    className="w-full"
                    aria-label={`Entry ${i + 1} take-profit`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TP_CHOICES.map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        TP{n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>
          {errors.stage_tp_map && (
            <p role="alert" className="text-sm text-destructive">
              {errors.stage_tp_map.message ?? "Each entry needs a TP from TP1 to TP5."}
            </p>
          )}
        </div>

        <NumberField
          id="default_sl_pips"
          label="Default stop-loss (pips)"
          help="Fallback SL when a signal omits one (1–500)."
          step="1"
          error={errors.default_sl_pips?.message}
          register={register("default_sl_pips", { valueAsNumber: true })}
        />

        <NumberField
          id="max_daily_trades"
          label="Daily trade limit"
          help="Maximum trades opened per day (1–100)."
          step="1"
          error={errors.max_daily_trades?.message}
          register={register("max_daily_trades", { valueAsNumber: true })}
        />

        <NumberField
          id="max_open_trades"
          label="Maximum open trades"
          help="Most positions open at once on one symbol, counting every signal (1–100). Must be at least Maximum entries per signal, or the extra entries never open."
          step="1"
          error={errors.max_open_trades?.message}
          register={register("max_open_trades", { valueAsNumber: true })}
        />

        {/* "Review changes" — opens the validate flow (does NOT persist). */}
        <Button type="submit" className="self-start">
          Review changes
        </Button>
      </form>
    </TooltipProvider>
  );
}

// ── Field helpers ───────────────────────────────────────────────────────────────────────────────

/** A label with an attached tooltip carrying units + recommended range + the server cap (SUX-02). */
function FieldLabel({
  htmlFor,
  label,
  help,
}: {
  htmlFor: string;
  label: string;
  help: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`${label} help`}
            className="flex size-4 items-center justify-center rounded-full border border-muted-foreground/40 text-[10px] leading-none text-muted-foreground hover:text-foreground"
          >
            ?
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">{help}</TooltipContent>
      </Tooltip>
    </div>
  );
}

/** A numeric input row: tooltip-helped label + number input + inline role="alert" error. */
function NumberField({
  id,
  label,
  help,
  step,
  error,
  register,
}: {
  id: string;
  label: string;
  help: string;
  step: string;
  error?: string;
  register: UseFormRegisterReturn;
}) {
  return (
    <div className="flex flex-col gap-2">
      <FieldLabel htmlFor={id} label={label} help={help} />
      <Input
        id={id}
        type="number"
        step={step}
        inputMode="decimal"
        aria-invalid={error ? "true" : undefined}
        {...register}
      />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
