import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { queryClient } from "@/app/queryClient";

export function renderWithRouter(routes: RouteObject[], initialEntries: string[] = ["/"]): ReactElement {
  const router = createMemoryRouter(routes, { initialEntries });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
