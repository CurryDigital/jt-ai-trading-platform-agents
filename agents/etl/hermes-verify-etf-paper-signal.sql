DO $$
DECLARE
    v_mode text;
    v_status text;
    v_universe int;
    v_capital numeric;
    v_se_count int;
    v_se_dir int;
    v_se_buy int;
    v_sts_count int;
    v_sts_paper int;
    v_weight_sum numeric;
    v_max_weight numeric;
    v_sig_active boolean;
    v_prl_positions int;
    v_fail int := 0;
BEGIN
    SELECT execution_mode, status, array_length(universe_tickers, 1), in_market_capital
    INTO v_mode, v_status, v_universe, v_capital
    FROM gold.strategy_registry
    WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation';

    IF v_mode IS DISTINCT FROM 'PAPER' THEN
        RAISE NOTICE 'FAIL: registry execution_mode expected=PAPER actual=%', v_mode;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: registry execution_mode=PAPER';
    END IF;

    IF v_status IS DISTINCT FROM 'paper' THEN
        RAISE NOTICE 'FAIL: registry status expected=paper actual=%', v_status;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: registry status=paper';
    END IF;

    IF v_universe IS DISTINCT FROM 3 THEN
        RAISE NOTICE 'FAIL: registry universe expected=3 actual=%', v_universe;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: registry universe=3';
    END IF;

    IF v_capital IS DISTINCT FROM 10000.00 THEN
        RAISE NOTICE 'FAIL: in_market_capital expected=10000.00 actual=%', v_capital;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: in_market_capital=10000.00';
    END IF;

    SELECT COUNT(*) INTO v_se_count
    FROM gold.signal_evaluations
    WHERE family_key = 'tactical' AND ticker IN ('IWM', 'VTEB', 'VTI');
    IF v_se_count IS DISTINCT FROM 3 THEN
        RAISE NOTICE 'FAIL: live signal_evaluations expected=3 actual=%', v_se_count;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: live signal_evaluations=3';
    END IF;

    SELECT COUNT(DISTINCT direction) INTO v_se_dir
    FROM gold.signal_evaluations
    WHERE family_key = 'tactical' AND ticker IN ('IWM', 'VTEB', 'VTI');
    IF v_se_dir IS DISTINCT FROM 1 THEN
        RAISE NOTICE 'FAIL: distinct directions expected=1 actual=%', v_se_dir;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: distinct directions=1';
    END IF;

    SELECT COUNT(*) INTO v_se_buy
    FROM gold.signal_evaluations
    WHERE family_key = 'tactical' AND ticker IN ('IWM', 'VTEB', 'VTI') AND direction = 'BUY';
    IF v_se_buy IS DISTINCT FROM 3 THEN
        RAISE NOTICE 'FAIL: BUY rows expected=3 actual=%', v_se_buy;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: BUY rows=3';
    END IF;

    SELECT COUNT(*) INTO v_sts_count
    FROM gold.strategy_ticker_scores
    WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation';
    IF v_sts_count IS DISTINCT FROM 3 THEN
        RAISE NOTICE 'FAIL: strategy_ticker_scores expected=3 actual=%', v_sts_count;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: strategy_ticker_scores=3';
    END IF;

    SELECT COUNT(*) INTO v_sts_paper
    FROM gold.strategy_ticker_scores
    WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation'
      AND criteria_met->>'execution_mode' = 'PAPER';
    IF v_sts_paper IS DISTINCT FROM 3 THEN
        RAISE NOTICE 'FAIL: PAPER criteria expected=3 actual=%', v_sts_paper;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: PAPER criteria=3';
    END IF;

    SELECT ROUND(SUM((criteria_met->>'weight')::numeric)::numeric, 6) INTO v_weight_sum
    FROM gold.strategy_ticker_scores
    WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation';
    IF ABS(v_weight_sum - 1) > 0.001 THEN
        RAISE NOTICE 'FAIL: weight sum expected=1 actual=%', v_weight_sum;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: weight sum ~= 1 (%)', v_weight_sum;
    END IF;

    SELECT MAX((criteria_met->>'weight')::numeric) INTO v_max_weight
    FROM gold.strategy_ticker_scores
    WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation';
    IF v_max_weight > 0.70 THEN
        RAISE NOTICE 'FAIL: max weight > 0.70: %', v_max_weight;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: max weight <= 0.70 (%)', v_max_weight;
    END IF;

    SELECT num_positions INTO v_prl_positions
    FROM gold.paper_run_log
    WHERE run_date = CURRENT_DATE AND status = 'ok'
    ORDER BY created_at DESC LIMIT 1;
    IF v_prl_positions IS DISTINCT FROM 3 THEN
        RAISE NOTICE 'FAIL: paper_run_log positions expected=3 actual=%', v_prl_positions;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: paper_run_log positions=3';
    END IF;

    SELECT active INTO v_sig_active
    FROM gold.strategy_signals
    WHERE strategy_id = 21
    ORDER BY date DESC LIMIT 1;
    IF v_sig_active IS DISTINCT FROM true THEN
        RAISE NOTICE 'FAIL: strategy_signals active expected=true actual=%', v_sig_active;
        v_fail := v_fail + 1;
    ELSE
        RAISE NOTICE 'PASS: strategy_signals active=true';
    END IF;

    IF v_fail = 0 THEN
        RAISE NOTICE 'ALL CHECKS PASSED';
    ELSE
        RAISE EXCEPTION 'SOME CHECKS FAILED: %', v_fail;
    END IF;
END $$;
