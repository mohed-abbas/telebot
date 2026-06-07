// frontend/src/routes/SettingsView.tsx — PAGE-08, the per-account Settings page (SUX-01..04).
//
// The two-step settings flow (D-05), end-to-end:
//   1. READ — useQuery(["settings", account], GET /api/v2/settings/{account}) → SettingsView
//      { values, audit, diff:null }. `values` are BARE typed values = the rhf defaultValues;
//      values.max_lot_size feeds the zod fixed_lot cap. Loading/ErrorPanel branch order from
//      StagedView (read failure → inline ErrorPanel, NOT a toast).
//   2. REVIEW — "Review changes" → useSettingsMutations.validate({account, values}). BRANCH ON
//      data.valid (Pitfall 7: the server returns 200 EVEN when valid:false — never branch on HTTP
//      status): invalid → toast.error("Couldn't save: {first error}"); valid → open ConfirmDiffDialog
//      with data.diff + data.dry_run_text.
//   3. CONFIRM — "Confirm change" → useSettingsMutations.confirm({account, values}) → success toast
//      (owned by the hook) → close modal → invalidate ["settings", account] (refetch values + audit).
//
// Account selection (per-account page): a shadcn select sourced from GET /api/v2/history/filter-options
// (accounts: string[]) — defaults to the first account. Switching account re-keys the settings query.
//
// The confirm Dialog renders outside any polling subtree (Settings does not poll — SC#3 naturally
// satisfied).

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ErrorPanel } from "@/components/state/ErrorPanel";
import { Loading } from "@/components/state/Loading";
import {
  SettingsForm,
  type SettingsFormValues,
  type SettingsServerValues,
} from "@/components/settings/SettingsForm";
import { ConfirmDiffDialog } from "@/components/settings/ConfirmDiffDialog";
import {
  AuditTimeline,
  type AuditEntry,
} from "@/components/settings/AuditTimeline";
import {
  useSettingsMutations,
  type SettingsValidateResult,
} from "@/hooks/useSettingsMutations";
import { api } from "@/lib/http";

// ── API types (RESEARCH §Settings contracts) ────────────────────────────────────────────────────

interface SettingsPayload {
  account: string;
  values: SettingsServerValues;
  audit: AuditEntry[];
  diff: null;
}

interface FilterOptions {
  accounts: string[];
  symbols: string[];
  sources: string[];
  directions: string[];
}

// ── Page ──────────────────────────────────────────────────────────────────────────────────────

export function SettingsView() {
  const qc = useQueryClient();
  const { validate, confirm } = useSettingsMutations();

  // Account list (for the per-account selector) — reuse the history filter-options accounts[].
  const { data: options } = useQuery<FilterOptions>({
    queryKey: ["history-filter-options"],
    queryFn: () => api("/api/v2/history/filter-options") as Promise<FilterOptions>,
  });

  const [account, setAccount] = useState<string | null>(null);

  // Default to the first available account once the list loads (until then, account is null).
  useEffect(() => {
    if (account == null && options?.accounts?.length) {
      setAccount(options.accounts[0]);
    }
  }, [account, options]);

  const accounts = options?.accounts ?? [];

  return (
    <div className="mx-auto max-w-3xl py-6">
      <div className="mb-6 flex items-center justify-between gap-4">
        <h2 className="text-xl font-semibold text-foreground">Settings</h2>
        {accounts.length > 0 && account != null && (
          <Select value={account} onValueChange={setAccount}>
            <SelectTrigger className="w-56">
              <SelectValue placeholder="Select account" />
            </SelectTrigger>
            <SelectContent>
              {accounts.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {account == null ? (
        <Loading rows={6} />
      ) : (
        <AccountSettings
          // CR-02: re-mount on account switch so rhf defaults AND all local review/confirm state
          // reset — without this, account A's typed values can be confirmed onto account B.
          key={account}
          account={account}
          validate={validate}
          confirm={confirm}
          invalidate={() =>
            qc.invalidateQueries({ queryKey: ["settings", account] })
          }
        />
      )}
    </div>
  );
}

// ── Per-account settings body (re-mounts/re-keys when the selected account changes) ─────────────

interface AccountSettingsProps {
  account: string;
  validate: ReturnType<typeof useSettingsMutations>["validate"];
  confirm: ReturnType<typeof useSettingsMutations>["confirm"];
  invalidate: () => void;
}

function AccountSettings({
  account,
  validate,
  confirm,
  invalidate,
}: AccountSettingsProps) {
  const { data, isPending, isError, error, refetch } = useQuery<SettingsPayload>({
    queryKey: ["settings", account],
    queryFn: () => api(`/api/v2/settings/${encodeURIComponent(account)}`) as Promise<SettingsPayload>,
  });

  // The pending change being reviewed (drives the confirm modal). Null = modal closed.
  const [review, setReview] = useState<SettingsFormValues | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // The diff + dry-run text to render in the confirm modal (set on a valid validate).
  const [confirmData, setConfirmData] = useState<{
    diff: SettingsValidateResult["diff"];
    dryRunText: string;
  } | null>(null);

  function handleReview(values: SettingsFormValues) {
    // REVIEW — validate is a dry-run. BRANCH ON data.valid (Pitfall 7: 200 even when invalid).
    validate.mutate(
      { account, values: { ...values } },
      {
        onSuccess: (result) => {
          if (!result.valid) {
            // Surface the first server error as a rejection toast (SUX-01). Never opens the modal.
            const first = Object.values(result.errors)[0] ?? "validation failed";
            toast.error(`Couldn't save: ${first}`);
            return;
          }
          // Valid → stash the change + the server diff/dry-run and open the confirm modal.
          setReview(values);
          setConfirmData({ diff: result.diff, dryRunText: result.dry_run_text });
          setConfirmOpen(true);
        },
      },
    );
  }

  function handleConfirm() {
    if (!review) return;
    // CONFIRM — persist. The success toast is owned by the hook; on success refetch + close.
    confirm.mutate(
      { account, values: { ...review } },
      {
        onSuccess: () => {
          invalidate();
          setConfirmOpen(false);
          setReview(null);
          setConfirmData(null);
        },
      },
    );
  }

  if (isPending) {
    return <Loading rows={6} />;
  }

  if (isError) {
    // Read failure → inline ErrorPanel (NOT a toast).
    return <ErrorPanel error={error} onRetry={() => refetch()} />;
  }

  const { values, audit } = data;

  return (
    <div className="flex flex-col gap-10">
      <SettingsForm values={values} onReview={handleReview} />

      <AuditTimeline account={account} audit={audit} />

      {review && confirmData && (
        <ConfirmDiffDialog
          open={confirmOpen}
          onOpenChange={(o) => {
            setConfirmOpen(o);
            // "Go back" closes the modal but PRESERVES the typed form values (the form owns them).
            if (!o) setReview(null);
          }}
          account={account}
          diff={confirmData.diff}
          dryRunText={confirmData.dryRunText}
          mode={review.risk_mode}
          riskValue={review.risk_value}
          maxStages={review.max_stages}
          onConfirm={handleConfirm}
          pending={confirm.isPending}
        />
      )}
    </div>
  );
}
