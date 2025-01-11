from ortools.linear_solver import pywraplp

def solve_material_substitution():
    # Create the solver
    solver = pywraplp.Solver.CreateSolver('GLOP')  # Linear programming solver

    if not solver:
        print("Solver not found!")
        return

    # Variables: quantities of materials x, y, z
    x = solver.NumVar(0, solver.infinity(), "x")
    y = solver.NumVar(0, solver.infinity(), "y")
    z = solver.NumVar(0, solver.infinity(), "z")

    # Material components
    components = {
        "x": [1, 1, 0],  # 1a, 1b, 0c
        "y": [2, 2, 0],  # 2a, 2b, 0c
        "z": [2, 0, 2],  # 2a, 0b, 2c
    }

    # Target components
    target = [4, 2, 2]  # 4a, 2b, 2c

    # Constraints: match the target components
    for i, component in enumerate(target):
        solver.Add(
            components["x"][i] * x +
            components["y"][i] * y +
            components["z"][i] * z == component
        )

    # Objective: Minimize the total material usage (optional)
    solver.Minimize(x + y + z)

    # Solve the problem
    status = solver.Solve()

    # Output results
    if status == pywraplp.Solver.OPTIMAL:
        print("Solution Found:")
        print(f"x = {x.solution_value()}")
        print(f"y = {y.solution_value()}")
        print(f"z = {z.solution_value()}")
        print("Total materials used:", x.solution_value() + y.solution_value() + z.solution_value())
    else:
        print("No solution found.")

# Run the solver
solve_material_substitution()
