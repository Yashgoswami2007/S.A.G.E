import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient();

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,

    defaultNotFoundComponent: () => (
      <div style={{ padding: "2rem" }}>
        <h1>404</h1>
        <p>Page not found.</p>
      </div>
    ),
  });

  return router;
};