import pulp

# Define the problem
problem = pulp.LpProblem("Material_Substitution", pulp.LpMinimize)

# Decision variables (quantities of each material)
x = pulp.LpVariable("x", lowBound=0, cat="Continuous")
y = pulp.LpVariable("y", lowBound=0, cat="Continuous")
z = pulp.LpVariable("z", lowBound=0, cat="Continuous")

# Material component definitions
components = {
    "x": {"a": 1, "b": 1, "c": 0},
    "y": {"a": 2, "b": 2, "c": 0},
    "z": {"a": 2, "b": 0, "c": 2},
}

# Input formula components (target to match)
target_components = {"a": 4, "b": 2, "c": 2}

# Constraints to match internal components
for component, target_value in target_components.items():
    problem += (
        components["x"][component] * x +
        components["y"][component] * y +
        components["z"][component] * z
        == target_value,
        f"Constraint_{component}"
    )

# Objective function: Minimize the deviation from the target (optional)
# Since we are matching exactly, we don't need to minimize anything specific.
# However, you could add something like minimizing the total material usage if needed.
problem += x + y + z, "Minimize_Total_Materials"

# Solve the problem
problem.solve()

# Print the results
print("Status:", pulp.LpStatus[problem.status])
print("Solution:")
print(f"x = {pulp.value(x)}")
print(f"y = {pulp.value(y)}")
print(f"z = {pulp.value(z)}")

# Verify the internal components
print("\nInternal Components:")
actual_components = {
    "a": components["x"]["a"] * pulp.value(x) + components["y"]["a"] * pulp.value(y) + components["z"]["a"] * pulp.value(z),
    "b": components["x"]["b"] * pulp.value(x) + components["y"]["b"] * pulp.value(y) + components["z"]["b"] * pulp.value(z),
    "c": components["x"]["c"] * pulp.value(x) + components["y"]["c"] * pulp.value(y) + components["z"]["c"] * pulp.value(z),
}
for component, value in actual_components.items():
    print(f"{component}: {value}")
