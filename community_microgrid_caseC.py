from __future__ import annotations

from pathlib import Path
from typing import Any

import cvxpy as cp
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DATA_PATH = Path(r"D:\workspace\EGS\Individual CW datasets\caseC_community_microgrid_hourly.csv")
OUTPUT_DIR = Path(r"D:\workspace\EGS\outputs_caseC")


def inspect_dataset(df: pd.DataFrame) -> dict[str, Any]:
    expected_columns = [
        "timestamp",
        "pv_kw",
        "load1_kw",
        "load2_kw",
        "load3_kw",
        "import_tariff_gbp_per_kwh",
        "export_price_gbp_per_kwh",
    ]
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    df = df.copy()
    df["load_total_kw"] = df["load1_kw"] + df["load2_kw"] + df["load3_kw"]

    timestep_hours = df["timestamp"].diff().dropna().dt.total_seconds() / 3600.0
    unique_steps = sorted(timestep_hours.unique().tolist())

    numeric_columns = [col for col in df.columns if col != "timestamp"]
    missing_values = df.isna().sum().to_dict()
    negative_counts = {col: int((df[col] < 0).sum()) for col in numeric_columns}

    summary = {
        "column_names": list(df.columns),
        "time_column": "timestamp",
        "pv_column": "pv_kw",
        "load_columns": ["load1_kw", "load2_kw", "load3_kw"],
        "import_tariff_column": "import_tariff_gbp_per_kwh",
        "export_price_column": "export_price_gbp_per_kwh",
        "dataset_length": int(len(df)),
        "unique_hour_steps": unique_steps,
        "is_hourly": unique_steps == [1.0],
        "missing_values": missing_values,
        "negative_counts": negative_counts,
        "min_values": df[numeric_columns].min().to_dict(),
        "max_values": df[numeric_columns].max().to_dict(),
    }
    return summary


def solve_dispatch(
    df: pd.DataFrame,
    battery_params: dict[str, float],
    terminal_mode: str = "equal",
    grid_import_limit_kw: float | None = None,
    preferred_solver: str = "CLARABEL",
) -> dict[str, Any]:
    dt = battery_params["dt"]
    pv = df["pv_kw"].to_numpy()
    load_total = (df["load1_kw"] + df["load2_kw"] + df["load3_kw"]).to_numpy()
    pi_imp = df["import_tariff_gbp_per_kwh"].to_numpy()
    pi_exp = df["export_price_gbp_per_kwh"].to_numpy()
    timestamps = df["timestamp"].to_numpy()
    n_steps = len(df)

    s_use = cp.Variable(n_steps, nonneg=True, name="s_use")
    p_ch = cp.Variable(n_steps, nonneg=True, name="p_ch")
    p_dis = cp.Variable(n_steps, nonneg=True, name="p_dis")
    g_imp = cp.Variable(n_steps, nonneg=True, name="g_imp")
    g_exp = cp.Variable(n_steps, nonneg=True, name="g_exp")
    energy = cp.Variable(n_steps + 1, name="E")

    constraints = []
    constraints.append(
        s_use + p_dis + g_imp == load_total + p_ch + g_exp
    )
    constraints.append(s_use + g_exp == pv)
    constraints.append(energy[0] == battery_params["E_init"])
    constraints.append(energy[1:] == energy[:-1] + battery_params["eta_ch"] * p_ch * dt - (1.0 / battery_params["eta_dis"]) * p_dis * dt)
    constraints.append(energy >= 0.0)
    constraints.append(energy <= battery_params["E_max"])
    constraints.append(p_ch <= battery_params["P_ch_max"])
    constraints.append(p_dis <= battery_params["P_dis_max"])
    constraints.append(s_use <= pv)

    if terminal_mode == "equal":
        constraints.append(energy[-1] == battery_params["E_init"])
    elif terminal_mode == "min_init":
        constraints.append(energy[-1] >= battery_params["E_init"])
    else:
        raise ValueError(f"Unsupported terminal mode: {terminal_mode}")

    if grid_import_limit_kw is not None:
        constraints.append(g_imp <= grid_import_limit_kw)

    objective = cp.Minimize(cp.sum(cp.multiply(pi_imp, g_imp) * dt - cp.multiply(pi_exp, g_exp) * dt))
    problem = cp.Problem(objective, constraints)

    solver_used = preferred_solver
    try:
        problem.solve(solver=preferred_solver, verbose=False)
    except Exception:
        solver_used = "SCS"
        problem.solve(solver=solver_used, verbose=False)

    if problem.status not in {"optimal", "optimal_inaccurate"}:
        raise RuntimeError(f"Optimisation failed with status {problem.status}")

    results = pd.DataFrame(
        {
            "timestamp": timestamps,
            "pv_kw": pv,
            "load_total_kw": load_total,
            "s_use_kw": s_use.value,
            "p_ch_kw": p_ch.value,
            "p_dis_kw": p_dis.value,
            "g_imp_kw": g_imp.value,
            "g_exp_kw": g_exp.value,
            "soc_start_kwh": energy.value[:-1],
            "soc_end_kwh": energy.value[1:],
            "import_tariff_gbp_per_kwh": pi_imp,
            "export_price_gbp_per_kwh": pi_exp,
        }
    )
    return {
        "problem_status": problem.status,
        "objective_value_gbp": float(problem.value),
        "solver_used": solver_used,
        "results": results,
        "terminal_mode": terminal_mode,
        "grid_import_limit_kw": grid_import_limit_kw,
        "battery_params": battery_params,
    }


def verify_solution(solution: dict[str, Any]) -> dict[str, Any]:
    results = solution["results"].copy()
    battery_params = solution["battery_params"]
    dt = battery_params["dt"]
    eta_ch = battery_params["eta_ch"]
    eta_dis = battery_params["eta_dis"]
    e_max = battery_params["E_max"]
    p_ch_max = battery_params["P_ch_max"]
    p_dis_max = battery_params["P_dis_max"]
    e_init = battery_params["E_init"]

    balance_error = (
        results["s_use_kw"]
        + results["p_dis_kw"]
        + results["g_imp_kw"]
        - (
            results["load_total_kw"]
            + results["p_ch_kw"]
            + results["g_exp_kw"]
        )
    )

    soc_series = np.concatenate(
        ([results["soc_start_kwh"].iloc[0]], results["soc_end_kwh"].to_numpy())
    )
    soc_lower_violation = np.maximum(0.0, -soc_series)
    soc_upper_violation = np.maximum(0.0, soc_series - e_max)

    p_ch_lower_violation = np.maximum(0.0, -results["p_ch_kw"].to_numpy())
    p_ch_upper_violation = np.maximum(0.0, results["p_ch_kw"].to_numpy() - p_ch_max)
    p_dis_lower_violation = np.maximum(0.0, -results["p_dis_kw"].to_numpy())
    p_dis_upper_violation = np.maximum(0.0, results["p_dis_kw"].to_numpy() - p_dis_max)

    pv_lower_violation = np.maximum(0.0, -results["s_use_kw"].to_numpy())
    pv_upper_violation = np.maximum(0.0, results["s_use_kw"].to_numpy() - results["pv_kw"].to_numpy())

    terminal_target = e_init
    final_soc = float(results["soc_end_kwh"].iloc[-1])
    if solution["terminal_mode"] == "equal":
        terminal_violation = abs(final_soc - terminal_target)
    else:
        terminal_violation = max(0.0, terminal_target - final_soc)

    import_cost = float(
        (results["g_imp_kw"] * results["import_tariff_gbp_per_kwh"] * dt).sum()
    )
    export_revenue = float(
        (results["g_exp_kw"] * results["export_price_gbp_per_kwh"] * dt).sum()
    )
    recomputed_net_cost = import_cost - export_revenue

    checks = {
        "max_abs_balance_error_kw": float(np.max(np.abs(balance_error))),
        "mean_abs_balance_error_kw": float(np.mean(np.abs(balance_error))),
        "max_soc_lower_violation_kwh": float(np.max(soc_lower_violation)),
        "max_soc_upper_violation_kwh": float(np.max(soc_upper_violation)),
        "max_charge_power_violation_kw": float(np.max(np.maximum(p_ch_lower_violation, p_ch_upper_violation))),
        "max_discharge_power_violation_kw": float(np.max(np.maximum(p_dis_lower_violation, p_dis_upper_violation))),
        "max_pv_limit_violation_kw": float(np.max(np.maximum(pv_lower_violation, pv_upper_violation))),
        "terminal_soc_violation_kwh": float(terminal_violation),
        "objective_value_gbp": float(solution["objective_value_gbp"]),
        "recomputed_net_cost_gbp": recomputed_net_cost,
        "cost_difference_gbp": float(abs(recomputed_net_cost - solution["objective_value_gbp"])),
        "unit_check_energy": "kW x h = kWh",
        "unit_check_cost": "GBP/kWh x kWh = GBP",
        "soc_update_equation": f"E_(t+1) = E_t + {eta_ch:.6f} * p_ch * dt - (1/{eta_dis:.6f}) * p_dis * dt",
    }

    if solution["grid_import_limit_kw"] is not None:
        limit = solution["grid_import_limit_kw"]
        binding_tolerance = 1e-4
        import_limit_violation = np.maximum(0.0, results["g_imp_kw"].to_numpy() - limit)
        binding_steps = int(np.sum(np.isclose(results["g_imp_kw"], limit, atol=binding_tolerance)))
        checks["max_grid_import_limit_violation_kw"] = float(np.max(import_limit_violation))
        checks["binding_timesteps"] = binding_steps

    return checks


def compute_kpis(solution: dict[str, Any]) -> dict[str, float]:
    results = solution["results"]
    dt = solution["battery_params"]["dt"]

    total_pv = float((results["pv_kw"] * dt).sum())
    pv_used = float((results["s_use_kw"] * dt).sum())
    pv_exported = float((results["g_exp_kw"] * dt).sum())
    grid_import = float((results["g_imp_kw"] * dt).sum())
    battery_charge = float((results["p_ch_kw"] * dt).sum())
    battery_discharge = float((results["p_dis_kw"] * dt).sum())
    total_load = float((results["load_total_kw"] * dt).sum())
    import_cost = float((results["g_imp_kw"] * results["import_tariff_gbp_per_kwh"] * dt).sum())
    export_revenue = float((results["g_exp_kw"] * results["export_price_gbp_per_kwh"] * dt).sum())
    soc_series = np.concatenate(
        ([results["soc_start_kwh"].iloc[0]], results["soc_end_kwh"].to_numpy())
    )
    initial_soc = float(soc_series[0])
    final_soc = float(soc_series[-1])
    soc_min = float(np.min(soc_series))
    soc_max = float(np.max(soc_series))
    throughput = battery_charge + battery_discharge
    battery_losses = max(0.0, battery_charge - battery_discharge)

    return {
        "total_pv_generation_kwh": total_pv,
        "pv_used_locally_kwh": pv_used,
        "pv_exported_kwh": pv_exported,
        "total_grid_import_kwh": grid_import,
        "total_battery_charge_kwh": battery_charge,
        "total_battery_discharge_kwh": battery_discharge,
        "total_community_load_kwh": total_load,
        "battery_net_losses_kwh": battery_losses,
        "import_cost_gbp": import_cost,
        "export_revenue_gbp": export_revenue,
        "net_total_cost_gbp": import_cost - export_revenue,
        "initial_soc_kwh": initial_soc,
        "final_soc_kwh": final_soc,
        "soc_min_kwh": soc_min,
        "soc_max_kwh": soc_max,
        "battery_throughput_kwh": throughput,
    }


def plot_raw_data(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df["timestamp"], df["pv_kw"], label="PV generation (kW)")
    ax.plot(df["timestamp"], df["load1_kw"], label="Load 1 (kW)")
    ax.plot(df["timestamp"], df["load2_kw"], label="Load 2 (kW)")
    ax.plot(df["timestamp"], df["load3_kw"], label="Load 3 (kW)")
    ax.set_title("Raw Dataset Sanity Check: PV and Household Loads")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power (kW)")
    ax.legend(loc="upper right", ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "raw_data_sanity_check.png", dpi=200)
    plt.close(fig)


def plot_solution(df: pd.DataFrame, solution: dict[str, Any], prefix: str) -> None:
    results = solution["results"]
    timestamps = pd.to_datetime(results["timestamp"])

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df["timestamp"], df["pv_kw"], label="PV (kW)")
    ax.plot(df["timestamp"], df["load1_kw"], label="Load 1 (kW)")
    ax.plot(df["timestamp"], df["load2_kw"], label="Load 2 (kW)")
    ax.plot(df["timestamp"], df["load3_kw"], label="Load 3 (kW)")
    ax.set_title(f"{prefix}: PV and Household Loads")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power (kW)")
    ax.legend(loc="upper right", ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_pv_and_loads.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(timestamps, results["load_total_kw"], label="Total community load (kW)")
    ax.plot(timestamps, results["pv_kw"], label="PV generation (kW)")
    ax.set_title(f"{prefix}: Total Load and PV")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power (kW)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_total_load_vs_pv.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    soc_series = np.concatenate(([results["soc_start_kwh"].iloc[0]], results["soc_end_kwh"].to_numpy()))
    soc_time = [timestamps.iloc[0]] + list(timestamps)
    ax.step(soc_time, soc_series, where="post")
    ax.set_title(f"{prefix}: Battery State of Charge")
    ax.set_xlabel("Time")
    ax.set_ylabel("Energy (kWh)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_soc.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(timestamps, results["p_ch_kw"], label="Charge power (kW)")
    ax.plot(timestamps, results["p_dis_kw"], label="Discharge power (kW)")
    ax.set_title(f"{prefix}: Battery Charge and Discharge Power")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power (kW)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_battery_power.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(timestamps, results["g_imp_kw"], label="Grid import (kW)")
    ax.plot(timestamps, results["g_exp_kw"], label="Grid export (kW)")
    if solution["grid_import_limit_kw"] is not None:
        ax.axhline(solution["grid_import_limit_kw"], color="red", linestyle="--", label="Import limit (kW)")
    ax.set_title(f"{prefix}: Grid Import and Export")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power (kW)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_grid_exchange.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(timestamps, results["import_tariff_gbp_per_kwh"], label="Import tariff (GBP/kWh)")
    ax.plot(timestamps, results["export_price_gbp_per_kwh"], label="Export price (GBP/kWh)")
    ax.set_title(f"{prefix}: Import Tariff and Export Price")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price (GBP/kWh)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_tariffs.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.stackplot(
        timestamps,
        results["s_use_kw"],
        results["p_dis_kw"],
        results["g_imp_kw"],
        labels=["PV used locally", "Battery discharge", "Grid import"],
        alpha=0.8,
    )
    ax.plot(timestamps, results["load_total_kw"] + results["p_ch_kw"] + results["g_exp_kw"], color="black", linewidth=1.0, label="Demand side total")
    ax.set_title(f"{prefix}: Supply-Demand Balance")
    ax.set_xlabel("Time")
    ax.set_ylabel("Power (kW)")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / f"{prefix}_supply_demand_balance.png", dpi=200)
    plt.close(fig)


def print_dict(title: str, values: dict[str, Any]) -> None:
    print(f"\n{title}")
    for key, value in values.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.6f}")
        else:
            print(f"  {key}: {value}")


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"])
    dataset_summary = inspect_dataset(df)
    plot_raw_data(df)

    eta = np.sqrt(0.90)
    battery_params = {
        "dt": 1.0,
        "E_max": 10.0,
        "P_ch_max": 5.0,
        "P_dis_max": 5.0,
        "eta_ch": float(eta),
        "eta_dis": float(eta),
        "E_init": 5.0,
    }

    feeder_import_limit_kw = 4.5

    base_solution = solve_dispatch(
        df=df,
        battery_params=battery_params,
        terminal_mode="equal",
        grid_import_limit_kw=None,
    )
    base_checks = verify_solution(base_solution)
    base_kpis = compute_kpis(base_solution)
    plot_solution(df, base_solution, "base_case")
    base_solution["results"].to_csv(OUTPUT_DIR / "base_case_results.csv", index=False)

    extension_solution = solve_dispatch(
        df=df,
        battery_params=battery_params,
        terminal_mode="equal",
        grid_import_limit_kw=feeder_import_limit_kw,
    )
    extension_checks = verify_solution(extension_solution)
    extension_kpis = compute_kpis(extension_solution)
    plot_solution(df, extension_solution, "extension_case")
    extension_solution["results"].to_csv(OUTPUT_DIR / "extension_case_results.csv", index=False)

    print_dict("DATASET SUMMARY", dataset_summary)
    print_dict("BATTERY PARAMETERS", battery_params)
    print_dict("BASE CASE VERIFICATION", base_checks)
    print_dict("BASE CASE KPIS", base_kpis)
    print_dict("EXTENSION VERIFICATION", extension_checks)
    print_dict("EXTENSION KPIS", extension_kpis)

    comparison = {
        "base_cost_gbp": base_kpis["net_total_cost_gbp"],
        "extension_cost_gbp": extension_kpis["net_total_cost_gbp"],
        "cost_increase_gbp": extension_kpis["net_total_cost_gbp"] - base_kpis["net_total_cost_gbp"],
        "base_grid_import_kwh": base_kpis["total_grid_import_kwh"],
        "extension_grid_import_kwh": extension_kpis["total_grid_import_kwh"],
        "base_battery_throughput_kwh": base_kpis["battery_throughput_kwh"],
        "extension_battery_throughput_kwh": extension_kpis["battery_throughput_kwh"],
        "extension_binding_timesteps": extension_checks.get("binding_timesteps", 0),
    }
    print_dict("BASE VS EXTENSION COMPARISON", comparison)


if __name__ == "__main__":
    main()
