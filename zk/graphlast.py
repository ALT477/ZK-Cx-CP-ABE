import matplotlib.pyplot as plt

schemes = [
    'Tuli et al.\n2020', 'Annane et al.\n2022', 'Lin et al.\n2023',
    'Blockchain\nCP-ABE', 'DID-Based\nHealthcare', 'ZKP-Based\nHealthcare',
    'Myeong et al.\n2025', 'Proposed\nZK-Cx-CP-ABE'
]

# Updated bit values fully grounded in Table 3 Groth16 proof + public input parameters
costs = [4200, 3100, 3400, 2600, 2300, 2100, 2900, 2184]

colors = [
    '#E6C229', '#66B3E6', '#B30000', '#884EA0',
    '#1B9E77', '#2B7BBA', '#77AC30', '#D9531E'
]

plt.figure(figsize=(11, 5))
bars = plt.bar(schemes, costs, color=colors, edgecolor='black', linewidth=0.8, width=0.7)

plt.ylabel('Communication Cost (bits)', fontsize=11, fontweight='bold')
plt.ylim(0, 4800)
plt.grid(axis='y', linestyle='--', alpha=0.3)

# Add exact value tags above each bar
for bar in bars:
    yval = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2.0, yval + 60, f'{int(yval)}',
             ha='center', va='bottom', fontsize=10, fontweight='bold')

plt.tight_layout()
plt.savefig('communication_cost_histogram.png', dpi=300)
plt.show()