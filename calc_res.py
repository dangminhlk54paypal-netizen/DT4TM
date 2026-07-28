import math
import yaml
with open('/Users/minh/VSCode_Repo/DT4TM/params.yaml', 'r') as f:
    params = yaml.safe_load(f)

coils = params['coils']
sigma = coils['sigma_Cu_S_per_m']
d = coils['wire_diameter_mm'] * 1e-3
A = math.pi * (d/2)**2

inner = coils['inner']
r_inner_avg = (inner['r_inner_mm'] + inner['r_outer_mm']) / 2 * 1e-3
L_inner = inner['turns'] * 2 * math.pi * r_inner_avg
R_inner = L_inner / (sigma * A)

outer = coils['outer']
r_outer_avg = (outer['r_inner_mm'] + outer['r_outer_mm']) / 2 * 1e-3
L_outer = outer['turns'] * 2 * math.pi * r_outer_avg
R_outer = L_outer / (sigma * A)

print(f"R_inner: {R_inner:.4f} ohm")
print(f"R_outer: {R_outer:.4f} ohm")
print(f"Total series: {R_inner + R_outer:.4f} ohm")
