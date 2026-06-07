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
// max_open_trades is shown READ-ONLY — it is an accounts-table column, not in validate_settings_form,
// so it is NOT in the editable/submitted field set (RESEARCH §max_open_trades note).
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
import { footgun } from "@/lib/footgun";
import { makeSettingsSchema } from "@/lib/settingsSchema";

// The EDITABLE/submitted field set (max_open_trades + max_lot_size are NOT here — read-only).
export interface SettingsFormValues {
  risk_mode: "percent" | "fixed_lot";
  risk_value: number;
  max_stages: number;
  default_sl_pips: number;
  max_daily_trades: number;
}

/** The full BARE server `values` dict (the GET response) — drives defaults + read-only fields. */
export interface SettingsServerValues extends SettingsFormValues {
  // Per-account cap (feeds the zod fixed_lot branch). Read-only — not editable, not submitted.
  max_lot_size: number;
  // Accounts-table column — read-only on this page (not in validate_settings_form).
  max_open_trades: number;
}

export interface SettingsFormProps {
  /** The bare server values from GET /api/v2/settings/{account}. */
  values: SettingsServerValues;
  /** Opens the two-step validate flow with the typed values. Does NOT persist. */
  onReview: (values: SettingsFormValues) => void;
}

export function SettingsForm({ values, onReview }: SettingsFormProps) {
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
    },
  });

  // Live mode-aware footgun inputs — re-render as these change (watch returns the current value).
  const mode = watch("risk_mode");
  const riskValue = watch("risk_value");
  const maxStages = watch("max_stages");

  const riskValueLabel =
    mode === "percent" ? "Per-trade risk (%)" : "Total lot size";
  const riskValueHelp =
    mode === "percent"
      ? `Percent of balance risked per trade. Max: 5.0%.`
      : `Total lots across all entries for this signal (not per trade). Max: ${values.max_lot_size}.`;

  // The inline footgun copy (mode-aware — percent multiplies; fixed_lot does NOT, Pitfall 6).
  // Guard against NaN-while-typing so the warning never renders garbage.
  const footgunText =
    Number.isFinite(riskValue) && Number.isFinite(maxStages)
      ? footgun(mode, riskValue, maxStages)
      : null;

  return (
    <TooltipProvider>
      <form
        onSubmit={handleSubmit(onReview)}
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

        {/* max_open_trades — READ-ONLY. Shown for context, never editable, never submitted. */}
        <div className="flex flex-col gap-2">
          <Label htmlFor="max_open_trades">Maximum open trades</Label>
          <Input
            id="max_open_trades"
            value={values.max_open_trades}
            readOnly
            disabled
            aria-readonly="true"
          />
          <p className="text-xs text-muted-foreground">
            Set per account — not editable here.
          </p>
        </div>

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
