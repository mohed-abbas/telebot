// frontend/src/hooks/useSettingsMutations.ts — the two-step settings flow (PAGE-08 / SUX-01).
//
// THE contract footgun (Pitfall 7 / T-11): the validate endpoint returns HTTP 200 EVEN WHEN the
// submitted settings are invalid — the failure is carried in the body as {valid:false, errors}.
// So `validate` MUST NOT route valid:false through onError. The mutation resolves normally and the
// PAGE reads `data.valid` to branch (show the diff + dry-run vs. show field errors). Throwing on
// valid:false here would turn an expected validation result into an error toast and break the flow.
//
// `confirm` and `revert` ARE ordinary mutations: a re-breached cap on confirm is a real 422 → toast;
// a 404 "Nothing to revert" surfaces via errorMessage(). Both invalidate ["settings", account].
//
// Shared discipline: api() only (CSRF — Pitfall 2), NO setQueryData (SC#1), 401 handled globally,
// errors via the shared errorMessage() envelope parser (T-11-06). Request bodies nest the field
// values under `values` for validate/confirm; revert carries {account} only.
//
// Server contracts:
//   POST /api/v2/settings/{account}/validate → SettingsValidateResult {valid, errors, diff, dry_run_text}
//        Body {account, values:{…}}. RETURNS 200 EVEN WHEN valid:false.
//   POST /api/v2/settings/{account}          → MutationResult {ok,success}. Body {account, values:{…}}.
//        Re-validates server-side; 422 if caps re-breached.
//   POST /api/v2/settings/{account}/revert   → MutationResult {ok,success}. Body {account}.
//        Inverts ONLY the latest change. 404 "Nothing to revert".

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/http";
import { errorMessage } from "@/components/state/ErrorPanel";

/** A single field-level change the server will apply, shown in the confirm diff. */
export interface SettingsDiffEntry {
  field: string;
  old: unknown;
  new: unknown;
}

/** The 200-body of /validate — valid:false is a SUCCESS body, NOT an error (Pitfall 7). */
export interface SettingsValidateResult {
  valid: boolean;
  errors: Record<string, string>;
  diff: SettingsDiffEntry[];
  dry_run_text: string;
}

export type SettingsValues = Record<string, unknown>;

export interface SettingsVars {
  account: string;
  values: SettingsValues;
}

export function useSettingsMutations() {
  const qc = useQueryClient();

  // Pitfall 7: validate resolves on BOTH valid:true and valid:false (server returns 200 either way).
  // The caller reads the returned `data.valid` to branch — we do NOT toast/throw on valid:false here.
  const validate = useMutation({
    mutationFn: ({ account, values }: SettingsVars) =>
      api(`/api/v2/settings/${account}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, values }),
      }) as Promise<SettingsValidateResult>,
    onError: (error) => {
      // Only a TRANSPORT/server failure (non-2xx) lands here — never a valid:false body.
      toast.error(errorMessage(error));
    },
  });

  const confirm = useMutation({
    mutationFn: ({ account, values }: SettingsVars) =>
      api(`/api/v2/settings/${account}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, values }),
      }),
    onSuccess: (_data, { account }) => {
      qc.invalidateQueries({ queryKey: ["settings", account] });
      toast.success(`Settings saved for ${account}.`);
    },
    onError: (error) => {
      // 422 if a cap was re-breached server-side — surfaced via the typed envelope.
      toast.error(errorMessage(error));
    },
  });

  const revert = useMutation({
    mutationFn: ({ account }: { account: string }) =>
      api(`/api/v2/settings/${account}/revert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account }),
      }),
    onSuccess: (_data, { account }) => {
      qc.invalidateQueries({ queryKey: ["settings", account] });
      toast.success(`Reverted last change for ${account}.`);
    },
    onError: (error) => {
      // 404 "Nothing to revert" surfaces via the shared envelope parser.
      toast.error(errorMessage(error));
    },
  });

  return { validate, confirm, revert };
}
