// frontend/src/components/settings/AuditTimeline.tsx — the settings audit timeline (PAGE-08).
//
// Renders audit[] from the SettingsView GET newest-first in the shared DataTable
// (Timestamp | Field | Change old→new | Actor), using timestamp_display (Pitfall 5 — the
// server-rendered display string, never a client-reformatted timestamp).
//
// REVERT is a SINGLE "Revert last change" action — NOT a per-row action, and it carries no
// per-row identifier (RESEARCH Open Question 1: the /revert endpoint inverts ONLY the latest
// persisted change and takes no row id; adding one would require a new endpoint = a boundary
// violation). The body is {account} only (useSettingsMutations.revert). It runs
// through a confirm dialog → useSettingsMutations.revert({account}); the success/error toast is owned
// by the hook ("Reverted last change for {account}." / "Nothing to revert").

import { useState } from "react";

import { DataTable, type Column } from "@/components/data/DataTable";
import { Empty } from "@/components/state/Empty";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useSettingsMutations } from "@/hooks/useSettingsMutations";

/** A single audit row from GET /api/v2/settings/{account} → audit[]. */
export interface AuditEntry {
  id: number;
  account_name: string;
  field: string;
  old_value: unknown;
  new_value: unknown;
  actor: string;
  timestamp: string;
  timestamp_display: string;
}

export interface AuditTimelineProps {
  account: string;
  audit: AuditEntry[];
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}

export function AuditTimeline({ account, audit }: AuditTimelineProps) {
  const { revert } = useSettingsMutations();
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Newest-first: the server may already order, but we sort defensively by id desc.
  const rows = [...audit].sort((a, b) => b.id - a.id);

  const columns: Column<AuditEntry>[] = [
    {
      header: "Timestamp",
      // Pitfall 5 — server display string only.
      cell: (r) => r.timestamp_display,
      mono: true,
    },
    { header: "Field", cell: (r) => r.field },
    {
      header: "Change",
      cell: (r) => (
        <span className="font-mono">
          <span className="text-muted-foreground">{fmt(r.old_value)}</span> →{" "}
          <span className="text-foreground">{fmt(r.new_value)}</span>
        </span>
      ),
    },
    {
      header: "Actor",
      cell: (r) => <span className="text-muted-foreground">{r.actor}</span>,
    },
  ];

  function handleRevert() {
    // Latest-only revert — body is {account} only, no per-row id (RESEARCH Open Question 1).
    revert.mutate({ account });
    setConfirmOpen(false);
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">
          Recent Changes
        </h3>
        {rows.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={revert.isPending}
          >
            Revert last change
          </Button>
        )}
      </div>

      {rows.length === 0 ? (
        <Empty
          title="No changes yet"
          message="Settings changes for this account will appear here."
        />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revert change — {account}</DialogTitle>
            <DialogDescription>
              This undoes the most recent settings change for {account}. It
              applies to signals received after you confirm; in-flight staged
              sequences are unaffected.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={revert.isPending}
            >
              Go back
            </Button>
            <Button onClick={handleRevert} disabled={revert.isPending}>
              {revert.isPending ? "Reverting…" : "Revert last change"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
