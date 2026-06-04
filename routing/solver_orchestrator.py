"""Solver orchestrator — selects the right solver based on problem size."""
from __future__ import annotations

from loguru import logger

from routing.schemas import VRPInput, VRPSolution
from infra.metrics import VRP_SOLVE_DURATION


class SolverOrchestrator:
    """Node-count-aware solver selection.

    <= 50 bins:  OR-Tools (30s) → SA fallback → greedy
    <= 200 bins: OR-Tools (20s) → SA (30k iter) fallback → greedy
    >  200 bins: SA (50k iter) directly → greedy
    """

    def __init__(
        self,
        ortools_time_limit: int = 30,
        sa_fallback: bool = True,
    ) -> None:
        self.ortools_time_limit = ortools_time_limit
        self.sa_fallback = sa_fallback

    async def solve(self, vrp_input: VRPInput) -> VRPSolution:
        """Always returns a valid VRPSolution — never raises."""
        n_bins = len(vrp_input.bins)

        with VRP_SOLVE_DURATION.time():
            try:
                if n_bins <= 50:
                    return self._solve_small(vrp_input)
                elif n_bins <= 200:
                    return self._solve_medium(vrp_input)
                else:
                    return self._solve_large(vrp_input)
            except Exception as exc:
                logger.error("SolverOrchestrator: all solvers failed ({}); returning greedy", exc)
                return self._greedy(vrp_input)

    # ------------------------------------------------------------------
    # Size-specific paths
    # ------------------------------------------------------------------

    def _solve_small(self, vrp: VRPInput) -> VRPSolution:
        """<= 50 bins: OR-Tools first, SA fallback, then greedy."""
        from routing.solver_ortools import solve_ortools

        vrp_ot = vrp.model_copy(update={"max_solve_seconds": self.ortools_time_limit})
        sol = solve_ortools(vrp_ot)

        if sol.solver == "ortools" and sol.status in ("optimal", "feasible"):
            logger.info("Orchestrator: OR-Tools succeeded ({} bins, {})", len(vrp.bins), sol.status)
            return sol

        if self.sa_fallback:
            logger.info("Orchestrator: OR-Tools insufficient for {} bins → SA", len(vrp.bins))
            return self._sa(vrp, max_iterations=50_000)

        return self._greedy(vrp)

    def _solve_medium(self, vrp: VRPInput) -> VRPSolution:
        """51-200 bins: OR-Tools (20s) first, SA (30k iter), then greedy."""
        from routing.solver_ortools import solve_ortools

        vrp_ot = vrp.model_copy(update={"max_solve_seconds": min(self.ortools_time_limit, 20)})
        sol = solve_ortools(vrp_ot)

        if sol.solver == "ortools" and sol.status in ("optimal", "feasible"):
            logger.info("Orchestrator: OR-Tools succeeded ({} bins, {})", len(vrp.bins), sol.status)
            return sol

        if self.sa_fallback:
            logger.info("Orchestrator: OR-Tools insufficient for {} bins → SA (30k)", len(vrp.bins))
            return self._sa(vrp, max_iterations=30_000)

        return self._greedy(vrp)

    def _solve_large(self, vrp: VRPInput) -> VRPSolution:
        """201+ bins: skip OR-Tools, go straight to SA (50k iter)."""
        logger.info("Orchestrator: {} bins — skipping OR-Tools, using SA", len(vrp.bins))
        if self.sa_fallback:
            return self._sa(vrp, max_iterations=50_000)
        return self._greedy(vrp)

    # ------------------------------------------------------------------
    # Solver wrappers
    # ------------------------------------------------------------------

    def _sa(self, vrp: VRPInput, max_iterations: int) -> VRPSolution:
        from routing.solvers.sa_solver import SimulatedAnnealingSolver

        try:
            solver = SimulatedAnnealingSolver(max_iterations=max_iterations)
            sol = solver.solve(vrp)
            logger.info(
                "Orchestrator: SA finished ({} bins, status={}, solve_ms={:.0f})",
                len(vrp.bins), sol.status, sol.solve_time_ms,
            )
            return sol
        except Exception as exc:
            logger.warning("Orchestrator: SA failed ({}) → greedy fallback", exc)
            return self._greedy(vrp)

    def _greedy(self, vrp: VRPInput) -> VRPSolution:
        from routing.solver_greedy import solve_greedy

        sol = solve_greedy(vrp)
        logger.info(
            "Orchestrator: greedy fallback ({} bins, status={})",
            len(vrp.bins), sol.status,
        )
        return sol
