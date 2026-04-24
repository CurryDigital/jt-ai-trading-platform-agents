"""
!! DEPRECATED — DO NOT IMPORT !!
================================
This file contains EXAMPLE agent implementations from an earlier architecture.
They use WRONG agent names (de_quant, algo_quant, qa_quant) and WRONG event
types (strategy.created, qa.failed, risk.approved).

The production agents live in agents/qr_*/  and use hub.sdk.Agent.

This file is preserved only as a reference. Do not run demo_workflow().
"""

raise ImportError(
    "hub.agents is deprecated. Production agents are in agents/qr_*/ directories. "
    "See agents/shared/constants.py for correct agent names."
)


class DEQuantAgent(Agent):
    """
    Quant Data Engineering Agent
    
    Domain: quant
    Handles:
    - strategy.created -> Prepares datasets
    - Emits: dataset.ready
    """
    
    def __init__(self):
        super().__init__("de_quant", domain="quant")
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == "strategy.created":
            self._prepare_dataset(event)
        else:
            logger.warning(f"DE agent received unexpected event: {event.event_type}")
    
    def _prepare_dataset(self, event: Event):
        """Prepare dataset for a new strategy."""
        strategy_id = event.strategy_id
        config = event.payload
        
        logger.info(f"DE: Preparing dataset for strategy {strategy_id}")
        
        # Simulate data preparation work
        dataset_version = f"dataset_v{config.get('version', '1')}"
        
        # Emit completion event
        self.emit_event(
            event_type="dataset.ready",
            strategy_id=strategy_id,
            payload={
                "dataset_version": dataset_version,
                "rows_processed": 1000000,
                "symbols": config.get("symbols", []),
                "date_range": config.get("date_range"),
                "prepared_by": "de"
            }
        )
        
        logger.info(f"DE: Dataset ready for strategy {strategy_id}")


class AlgoQuantAgent(Agent):
    """
    Quant Algorithm Agent
    
    Domain: quant
    Handles:
    - dataset.ready -> Runs backtests
    - Emits: backtest.completed
    - Records: strategy lineage
    """
    
    def __init__(self):
        super().__init__("algo_quant", domain="quant")
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == "dataset.ready":
            self._run_backtest(event)
        else:
            logger.warning(f"Algo agent received unexpected event: {event.event_type}")
    
    def _run_backtest(self, event: Event):
        """Run backtest on prepared dataset."""
        strategy_id = event.strategy_id
        dataset_info = event.payload
        
        logger.info(f"Algo: Running backtest for strategy {strategy_id}")
        
        # Simulate backtest execution
        strategy_params = {
            "lookback": 20,
            "entry_threshold": 1.5,
            "exit_threshold": 0.5,
            "position_size": 0.1
        }
        
        backtest_results = {
            "sharpe": 1.42,
            "drawdown": -0.08,
            "trades": 213,
            "win_rate": 0.58,
            "profit_factor": 1.8
        }
        
        # Record lineage for reproducibility
        self.lineage.record(
            strategy_id=strategy_id,
            dataset_version=dataset_info["dataset_version"],
            backtest_engine_version="engine_v2.1",
            strategy_parameters=strategy_params,
            result_metrics=backtest_results,
            source_event_id=event.id
        )
        
        # Emit completion event
        self.emit_event(
            event_type="backtest.completed",
            strategy_id=strategy_id,
            payload={
                "results": backtest_results,
                "dataset_version": dataset_info["dataset_version"],
                "parameters": strategy_params,
                "tested_by": "algo"
            }
        )
        
        logger.info(f"Algo: Backtest completed for strategy {strategy_id}")


class QAQuantAgent(Agent):
    """
    Quant Quality Assurance Agent
    
    Domain: quant
    Handles:
    - backtest.completed -> Validates results
    - Emits: qa.validated or qa.failed
    """
    
    def __init__(self):
        super().__init__("qa_quant", domain="quant")
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == "backtest.completed":
            self._validate_backtest(event)
        else:
            logger.warning(f"QA agent received unexpected event: {event.event_type}")
    
    def _validate_backtest(self, event: Event):
        """Validate backtest results."""
        strategy_id = event.strategy_id
        results = event.payload
        
        logger.info(f"QA: Validating backtest for strategy {strategy_id}")
        
        # Simulate validation checks
        issues = []
        
        if results["results"]["sharpe"] < 1.0:
            issues.append("Sharpe ratio below threshold (1.0)")
        
        if results["results"]["drawdown"] < -0.15:
            issues.append("Max drawdown exceeds limit (-15%)")
        
        if results["results"]["trades"] < 50:
            issues.append("Insufficient trade sample (< 50)")
        
        # Emit validation result
        if issues:
            self.emit_event(
                event_type="qa.failed",
                strategy_id=strategy_id,
                payload={
                    "issues": issues,
                    "results": results,
                    "validated_by": "qa"
                }
            )
            logger.warning(f"QA: Validation FAILED for strategy {strategy_id}")
        else:
            self.emit_event(
                event_type="qa.validated",
                strategy_id=strategy_id,
                payload={
                    "verdict": "PASSED",
                    "results": results,
                    "validated_by": "qa"
                }
            )
            logger.info(f"QA: Validation PASSED for strategy {strategy_id}")


class PlatformQuantAgent(Agent):
    """
    Quant Platform Agent (Research Deployment)
    
    Domain: quant
    Handles:
    - risk.approved -> Deploys strategy
    - Emits: platform.deployed
    """
    
    def __init__(self):
        super().__init__("platform_quant", domain="quant")
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == "qa.validated":
            self._deploy_strategy(event)
        else:
            logger.warning(f"Platform agent received unexpected event: {event.event_type}")
    
    def _deploy_strategy(self, event: Event):
        """Deploy validated strategy."""
        strategy_id = event.strategy_id
        validation = event.payload
        
        logger.info(f"Platform: Deploying strategy {strategy_id}")
        
        # Simulate deployment
        deployment_info = {
            "endpoint": f"/api/strategies/{strategy_id}",
            "environment": "production",
            "version": "1.0.0",
            "deployed_at": "2026-03-17T00:00:00Z"
        }
        
        # Emit completion event
        self.emit_event(
            event_type="platform.deployed",
            strategy_id=strategy_id,
            payload={
                "deployment": deployment_info,
                "validation": validation,
                "deployed_by": "platform"
            }
        )
        
        logger.info(f"Platform: Strategy {strategy_id} deployed successfully")


# Example: Manual event emission for testing
def demo_workflow():
    """
    Demo the full quant workflow by emitting events manually.
    """
    print("=== Demo: Full Quant Strategy Workflow ===\n")
    
    # Step 1: Strategy created (could come from TradingHub or human)
    print("1. Creating strategy...")
    emit_event(
        event_type="strategy.created",
        strategy_id="demo_104",
        payload={
            "name": "Momentum Strategy",
            "symbols": ["AAPL", "MSFT", "GOOGL"],
            "date_range": ["2024-01-01", "2024-12-31"],
            "version": "1"
        },
        source_agent="tradinghub",
        domain="quant"
    )
    
    # Step 2: DE processes (would run as separate agent)
    print("2. DE Quant processing...")
    de = DEQuantAgent()
    de.run()  # Processes pending events
    
    # Step 3: Algo processes
    print("3. Algo Quant processing...")
    algo = AlgoQuantAgent()
    algo.run()
    
    # Step 4: QA processes
    print("4. QA Quant processing...")
    qa = QAQuantAgent()
    qa.run()
    
    # Step 5: Platform processes
    print("5. Platform Quant processing...")
    platform = PlatformQuantAgent()
    platform.run()
    
    print("\n=== Workflow Complete ===")


if __name__ == "__main__":
    # Run demo if executed directly
    demo_workflow()
