% Define materials and their components
material(x, [1*a, 1*b]).
material(y, [2*a, 2*b]).
material(z, [2*a, 2*c]).

% Compute the internal components for a given material and quantity
components([], []).
components([Q*Material|Rest], Components) :-
    material(Material, MatComponents),
    scale_components(Q, MatComponents, ScaledComponents),
    components(Rest, RestComponents),
    merge_components(ScaledComponents, RestComponents, Components).

% Scale the components of a material
scale_components(_, [], []).
scale_components(Q, [Q1*C|Rest], [Q2*C|ScaledRest]) :-
    Q2 is Q * Q1,
    scale_components(Q, Rest, ScaledRest).

% Merge two lists of components (combine quantities of same components)
merge_components([], Components, Components).
merge_components([Q1*C|Rest1], Components2, [Q*C|MergedRest]) :-
    select(Q2*C, Components2, Rest2), !,
    Q is Q1 + Q2,
    merge_components(Rest1, Rest2, MergedRest).
merge_components([Q1*C|Rest1], Components2, [Q1*C|MergedRest]) :-
    merge_components(Rest1, Components2, MergedRest).

% Check if two lists of components are equivalent
equivalent_components([], []).
equivalent_components([Q1*C|Rest1], Components2) :-
    select(Q2*C, Components2, Rest2),
    Q1 =:= Q2,
    equivalent_components(Rest1, Rest2).

% Solve for substitution to match components
solve_substitution(Input, Target, Substitution) :-
    components(Input, InputComponents),
    components(Target, TargetComponents),
    equivalent_components(InputComponents, TargetComponents),
    Substitution = Target.

% Example query to find a substitution
example :-
    Input = [2*x, 1*z],
    Target = [1*y, 1*z],
    solve_substitution(Input, Target, Substitution),
    write('Substitution: '), write(Substitution), nl.
