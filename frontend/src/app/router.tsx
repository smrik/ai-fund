import { createBrowserRouter, Navigate } from "react-router-dom";

import { RootLayout } from "@/components/RootLayout";
import { TickerLayout } from "@/components/TickerLayout";
import { AuditPage } from "@/pages/AuditPage";
import { MarketPage } from "@/pages/MarketPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { ResearchPage } from "@/pages/ResearchPage";
import { ValuationPage } from "@/pages/ValuationPage";
import { WatchlistPage } from "@/pages/WatchlistPage";

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { index: true, element: <Navigate to="/watchlist" replace /> },
      { path: "watchlist", element: <WatchlistPage /> },
      {
        path: "ticker/:ticker",
        element: <TickerLayout />,
        children: [
          { index: true, element: <Navigate to="overview" replace /> },
          { path: "overview", element: <OverviewPage /> },
          { path: "valuation", element: <ValuationPage /> },
          { path: "market", element: <MarketPage /> },
          { path: "research", element: <ResearchPage /> },
          { path: "audit", element: <AuditPage /> },
        ],
      },
      { path: "*", element: <Navigate to="/watchlist" replace /> },
    ],
  },
]);
