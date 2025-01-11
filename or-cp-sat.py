from ortools.sat.python import cp_model

def solve_material_substitution_cp_sat():
    # Create the model
    model = cp_model.CpModel()

    # Decision variables: quantities of materials x, y, z (integer variables)
    x = model.NewIntVar(0, 10, "x")  # Arbitrary upper bound
    y = model.NewIntVar(0, 10, "y")
    z = model.NewIntVar(0, 10, "z")

    # Material components
    components = {
        "x": [1, 1, 0],  # 1a, 1b, 0c
        "y": [2, 2, 0],  # 2a, 2b, 0c
        "z": [2, 0, 2],  # 2a, 0b, 2c
    }

    # Target components
    target = [4, 2, 2]  # 4a, 2b, 2c

    # Constraints to match target components
    for i in range(len(target)):
        model.Add(
            components["x"][i] * x +
            components["y"][i] * y +
            components["z"][i] * z == target[i]
        )

    # Objective: Minimize the total material usage
    model.Minimize(x + y + z)

    # Solve the model
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    # Print the results
    if status == cp_model.OPTIMAL:
        print("Optimal Solution Found:")
        print(f"x = {solver.Value(x)}")
        print(f"y = {solver.Value(y)}")
        print(f"z = {solver.Value(z)}")
        print("Total materials used:", solver.Value(x) + solver.Value(y) + solver.Value(z))
    else:
        print("No solution found.")

# Run the solver
solve_material_substitution_cp_sat()
