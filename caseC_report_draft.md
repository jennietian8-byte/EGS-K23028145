# Case C: Community Microgrid Coursework Draft

## 1. Introduction

This coursework models a community microgrid comprising one shared PV system, one shared battery, three household electrical loads, and a single grid connection. The purpose of the model is to determine an hourly dispatch schedule that minimises total community electricity cost while respecting battery operating limits and a physically consistent energy balance.

Community microgrids are relevant because they coordinate distributed generation, storage, and demand behind a common point of connection. In this case, the shared battery can improve PV self-consumption, reduce costly grid imports during expensive tariff periods, and shift energy across time. The work follows the taught modelling sequence:

Physical system -> Mathematical abstraction -> Executable code -> Verified results.

It also follows the five-layer pipeline:

Data layer -> Model layer -> Solve layer -> Verification layer -> Output layer.

## 2. Dataset and Assumptions

### 2.1 Dataset contents

The dataset `caseC_community_microgrid_hourly.csv` contains 336 records, corresponding to 14 days of hourly operation. The identified columns are:

- `timestamp`: time index
- `pv_kw`: community PV generation in kW
- `load1_kw`, `load2_kw`, `load3_kw`: three household loads in kW
- `import_tariff_gbp_per_kwh`: grid import price in GBP/kWh
- `export_price_gbp_per_kwh`: grid export price in GBP/kWh

The total community load is defined as:

\[
L_{\text{tot},t} = L_{1,t} + L_{2,t} + L_{3,t}
\]

Dataset checks showed:

- 336 rows
- constant 1 hour timestep
- no missing values
- no negative values in PV, loads, or prices
- all model input series have equal length

The data values are already consistent with the coursework units: power in kW and prices in GBP/kWh.

### 2.2 Battery parameters

The shared battery parameters were set to the coursework defaults:

- usable capacity, \(E_{\max} = 10\) kWh
- maximum charge power, \(P_{\text{ch,max}} = 5\) kW
- maximum discharge power, \(P_{\text{dis,max}} = 5\) kW
- round-trip efficiency = 90%
- \(\eta_{\text{ch}} = \eta_{\text{dis}} = \sqrt{0.9} = 0.948683\)
- initial state of charge, \(E_0 = 5\) kWh
- timestep, \(\Delta t = 1\) h
- grid charging allowed

### 2.3 Metering and modelling assumptions

The metering assumption used throughout is:

"Single community meter at the grid connection; all three household loads are aggregated at community level for dispatch optimisation."

Additional assumptions:

- the system is modelled as a single-node electricity bus
- no load shedding is allowed
- no battery degradation cost is included
- PV curtailment is not used because export is allowed
- terminal state of charge is enforced as \(E_T = E_0\) so that the optimiser cannot reduce cost by emptying the battery at the end of the horizon
- PV is split between local use and export using \(s_{\text{use},t} + g_{\text{exp},t} = PV_t\), which makes the PV-use KPIs physically interpretable

## 3. Model Formulation

### 3.1 Indices

\[
t = 1,2,\dots,T
\]

with \(T = 336\).

### 3.2 Parameters

\[
PV_t,\; L_{1,t},\; L_{2,t},\; L_{3,t},\; L_{\text{tot},t},\; \pi_{\text{imp},t},\; \pi_{\text{exp},t}
\]

\[
\Delta t,\; E_{\max},\; P_{\text{ch,max}},\; P_{\text{dis,max}},\; \eta_{\text{ch}},\; \eta_{\text{dis}},\; E_{\text{init}}
\]

where:

\[
L_{\text{tot},t} = L_{1,t} + L_{2,t} + L_{3,t}
\]

### 3.3 Decision variables

\[
s_{\text{use},t},\; p_{\text{ch},t},\; p_{\text{dis},t},\; g_{\text{imp},t},\; g_{\text{exp},t},\; E_t
\]

where:

- \(s_{\text{use},t}\) is PV used within the community bus
- \(p_{\text{ch},t}\) is battery charging power
- \(p_{\text{dis},t}\) is battery discharging power
- \(g_{\text{imp},t}\) is grid import power
- \(g_{\text{exp},t}\) is grid export power
- \(E_t\) is battery stored energy

### 3.4 Objective function

The community objective is to minimise total electricity cost:

\[
\min \sum_{t=1}^{T}\left(\pi_{\text{imp},t} g_{\text{imp},t} - \pi_{\text{exp},t} g_{\text{exp},t}\right)\Delta t
\]

### 3.5 Constraints

Hourly energy balance:

\[
s_{\text{use},t} + p_{\text{dis},t} + g_{\text{imp},t} = L_{\text{tot},t} + p_{\text{ch},t} + g_{\text{exp},t}
\]

Battery state update:

\[
E_{t+1} = E_t + \eta_{\text{ch}} p_{\text{ch},t}\Delta t - \frac{1}{\eta_{\text{dis}}} p_{\text{dis},t}\Delta t
\]

State-of-charge bounds:

\[
0 \le E_t \le E_{\max}
\]

Charge and discharge power bounds:

\[
0 \le p_{\text{ch},t} \le P_{\text{ch,max}}
\]

\[
0 \le p_{\text{dis},t} \le P_{\text{dis,max}}
\]

PV utilisation bounds:

\[
0 \le s_{\text{use},t} \le PV_t
\]

PV allocation:

\[
s_{\text{use},t} + g_{\text{exp},t} = PV_t
\]

Grid non-negativity:

\[
g_{\text{imp},t} \ge 0,\qquad g_{\text{exp},t} \ge 0
\]

Initial condition:

\[
E_0 = E_{\text{init}}
\]

Terminal condition:

\[
E_T = E_{\text{init}}
\]

The equality terminal condition is preferred here because it prevents the final battery energy from acting as a hidden subsidy to the objective. This makes cost comparisons between scenarios fair and repeatable.

## 4. Implementation

The implementation was completed in Python using:

- `pandas` for data handling
- `numpy` for array operations
- `matplotlib` for plots
- `cvxpy` for linear programming

The code is organised into six blocks:

1. data loading and inspection
2. parameter definition
3. optimisation model creation
4. solver execution
5. post-processing and KPI calculation
6. verification and plotting

The optimisation was solved with the `CLARABEL` solver through `cvxpy`, with `SCS` included as a fallback option if the preferred solver fails. This satisfies the requirement for a linear programming implementation while keeping the model directly traceable to the mathematical equations.

## 5. Verification

Verification was treated as a separate stage rather than assumed implicitly from solver success.

### 5.1 Base-case verification evidence

- maximum absolute energy-balance error: 0.000000 kW
- mean absolute energy-balance error: 0.000000 kW
- maximum SOC lower-bound violation: 0.000000 kWh
- maximum SOC upper-bound violation: 0.000000 kWh
- maximum charge-power violation: 0.000000 kW
- maximum discharge-power violation: 0.000000 kW
- maximum PV-limit violation: 0.000000 kW
- terminal SOC violation: 0.000000 kWh
- optimisation objective: 85.020517 GBP
- recomputed total cost from outputs: 85.020517 GBP
- objective mismatch: 0.000000 GBP

### 5.2 Extension-case verification evidence

- maximum absolute energy-balance error: 0.000000 kW
- mean absolute energy-balance error: 0.000000 kW
- maximum SOC lower-bound violation: 0.000000 kWh
- maximum SOC upper-bound violation: 0.000000 kWh
- maximum charge-power violation: 0.000000 kW
- maximum discharge-power violation: 0.000000 kW
- maximum PV-limit violation: 0.000000 kW
- terminal SOC violation: 0.000000 kWh
- maximum feeder-limit violation: 0.000000 kW
- feeder-binding timesteps: 60

### 5.3 Unit consistency

The unit checks are explicit:

- energy from power: \( \text{kW} \times \text{h} = \text{kWh} \)
- cost from tariff and energy: \( \text{GBP/kWh} \times \text{kWh} = \text{GBP} \)

These checks matter because the dispatch is computed in power variables but reported in energy and cost. An incorrect unit conversion would invalidate the KPI totals even if the optimisation solved numerically.

## 6. Results and Discussion

### 6.1 Base-case energy breakdown

- total PV generation: 839.324 kWh
- PV used locally: 784.650 kWh
- PV exported: 54.674 kWh
- total grid import: 694.033 kWh
- battery charge energy: 199.590 kWh
- battery discharge energy: 179.631 kWh
- total community load: 1404.050 kWh
- battery losses: 19.959 kWh

The PV utilisation ratio is:

\[
\frac{784.650}{839.324} = 93.5\%
\]

This indicates high PV self-consumption once the shared battery is available.

### 6.2 Base-case cost breakdown

- import cost: 88.126 GBP
- export revenue: 3.105 GBP
- net total cost: 85.021 GBP

### 6.3 Battery contribution relative to a no-battery reference

A no-battery reference dispatch was solved using the same PV, load, and tariff data. That reference case gave:

- net cost: 119.077 GBP
- grid import: 784.724 kWh
- grid export: 109.999 kWh

Therefore, adding the shared battery reduced:

- net cost by 34.056 GBP over the 14-day horizon
- grid import by 90.691 kWh
- PV export by 55.325 kWh

This demonstrates that the battery primarily increases PV self-consumption and reduces high-tariff imports rather than creating export revenue.

### 6.4 Dispatch interpretation

The battery cycles between 0 and 10 kWh, so the storage capacity is actively used. Total throughput is 379.221 kWh over 336 hours, showing frequent cycling. The battery charges during periods of PV surplus and, where economically beneficial, during lower-tariff periods. It then discharges during higher-tariff hours and evening demand peaks.

The import tariff reaches 0.3145 GBP/kWh while export prices remain much lower, with a maximum of 0.0635 GBP/kWh. This tariff spread explains why the battery is more valuable for import avoidance than for export arbitrage. In engineering terms, the battery mainly performs:

- self-consumption improvement
- time-shifting of low-cost or solar energy
- partial peak shaving during evening demand peaks

## 7. Extension: Feeder Import Limit

### 7.1 Extension definition

The extension introduces a feeder import limit:

\[
P_{\text{grid,imp,max}} = 4.5 \text{ kW}
\]

This value was chosen from the observed data as a realistic constrained feeder capacity. The unconstrained solution reaches a maximum grid import of 10.686 kW, while the maximum net load without storage reaches 6.427 kW. A 4.5 kW limit is therefore sufficiently restrictive to change dispatch, but still feasible because the battery can supply the remaining demand during constrained periods.

The new constraint is:

\[
0 \le g_{\text{imp},t} \le P_{\text{grid,imp,max}}
\]

### 7.2 Extension verification

The extension remained feasible with no unmet demand and no SOC or power-limit violations. The additional verification results were:

- maximum feeder-limit violation: 0.000000 kW
- binding timesteps: 60
- extension maximum grid import: 4.500 kW

The feeder limit binds mainly in evening hours, especially around 20:00 to 22:00, with some additional early-morning constrained periods.

### 7.3 Base-case versus extension comparison

- base cost: 85.021 GBP
- extension cost: 89.748 GBP
- cost increase: 4.728 GBP
- base grid import: 694.033 kWh
- extension grid import: 690.402 kWh
- base battery throughput: 379.221 kWh
- extension battery throughput: 310.230 kWh

The feeder cap reduces allowable import peaks, so the optimiser must reserve battery energy for constrained periods. This causes a more conservative battery schedule and raises total cost. Although total imported energy falls slightly, the main operational effect is not energy reduction but power reshaping.

### 7.4 Engineering interpretation of the extension

The feeder constraint changes the role of the shared battery. In the base case, the battery is mainly scheduled against time-varying tariffs and PV surplus. Under the feeder cap, the battery also becomes a network support asset. It must protect the community against import-limit breaches during periods of high simultaneous load and weak PV output.

This result is important engineeringly because network constraints can increase the strategic value of community storage even when the total imported energy changes very little. The trade-off is that a battery reserved for feeder support may be less free to pursue pure cost-minimising arbitrage.

## 8. Conclusion

The model successfully formulated and solved a community-level dispatch problem for a shared PV and battery microgrid using an hourly linear programme. The final workflow is reproducible, physically transparent, and fully verified.

The main findings are:

- the shared battery raises PV self-consumption to 93.5%
- the battery reduces net cost from 119.077 GBP to 85.021 GBP compared with a no-battery reference
- the battery reduces grid imports and shifts energy from low-value periods to high-value periods
- enforcing \(E_T = E_0\) prevents hidden end effects and supports fair comparison
- the 4.5 kW feeder import limit binds 60 times and raises net cost to 89.748 GBP

The main limitations are the single-node representation, the absence of battery degradation cost, and the lack of household-level fairness metrics. These would be natural future improvements if a more detailed model were required.

## 9. AI Usage Statement Template

I used generative AI as a support tool to help structure the modelling workflow, improve code readability, and draft report text. I independently checked the dataset interpretation, implemented and ran the optimisation model, reviewed the verification outputs, and edited the final submission to ensure that the modelling assumptions, equations, numerical results, and engineering discussion accurately reflect my own work.
