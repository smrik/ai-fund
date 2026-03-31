import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet, useNavigate, useParams } from "react-router-dom";

import { TickerTabs } from "@/components/TickerTabs";
import { getTickerWorkspace, openLatestSnapshot, runDeepAnalysis } from "@/lib/api";
import { snapshotToOverview, snapshotToWorkspace } from "@/lib/snapshot";
import type { OverviewPayload, TickerWorkspace } from "@/lib/types";

export function TickerLayout() {
  const { ticker = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const workspaceQuery = useQuery({
    queryKey: ["ticker-workspace", ticker],
    queryFn: () => getTickerWorkspace(ticker),
    enabled: Boolean(ticker),
  });

  const openLatestSnapshotMutation = useMutation({
    mutationFn: () => openLatestSnapshot(ticker),
    onSuccess: async (payload) => {
      queryClient.setQueryData(
        ["ticker-workspace", ticker],
        (previous: TickerWorkspace | undefined) => snapshotToWorkspace(payload, previous),
      );
      queryClient.setQueryData(
        ["ticker-overview", ticker],
        (previous: OverviewPayload | undefined) => snapshotToOverview(payload, previous),
      );
      await queryClient.invalidateQueries({ queryKey: ["ticker-workspace", ticker] });
      await queryClient.invalidateQueries({ queryKey: ["ticker-overview", ticker] });
      await queryClient.invalidateQueries({ queryKey: ["ticker-valuation-summary", ticker] });
      navigate("overview");
    },
  });

  const runDeepAnalysisMutation = useMutation({
    mutationFn: () => runDeepAnalysis(ticker),
  });

  const workspace = workspaceQuery.data;
  const handleOpenLatestSnapshot = () => openLatestSnapshotMutation.mutate();
  const handleRunDeepAnalysis = () => runDeepAnalysisMutation.mutate();

  return (
    <section className="ticker-layout">
      <TickerTabs />

      <Outlet
        context={{
          workspace,
          openLatestSnapshot: handleOpenLatestSnapshot,
          runDeepAnalysis: handleRunDeepAnalysis,
          openLatestSnapshotPending: openLatestSnapshotMutation.isPending,
          runDeepAnalysisPending: runDeepAnalysisMutation.isPending,
        }}
      />
    </section>
  );
}
