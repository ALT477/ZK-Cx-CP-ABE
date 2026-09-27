import matplotlib.pyplot as plt

# X-Axis Data
requests = [100, 500, 1000, 5000]

# Real Network Response Times (ms)
tuli = [98.60, 119.30, 147.20, 289.40]
lin = [91.20, 110.50, 138.40, 268.10]
annane = [86.40, 103.20, 129.50, 245.30]
blockchain_cpabe = [79.80, 98.40, 121.00, 224.60]
myeong = [74.50, 92.10, 112.60, 208.40]
did_healthcare = [72.50, 89.10, 108.30, 198.50]
zkp_healthcare = [68.20, 81.50, 98.40, 175.20]
proposed = [53.40, 58.15, 67.30, 128.50]

fig, ax = plt.subplots(figsize=(11, 6))

ax.plot(requests, tuli, marker='o', color='#1f77b4', linewidth=1.8, label='Tuli et al. 2020')
ax.plot(requests, lin, marker='o', color='#2ca02c', linewidth=1.8, label='Lin et al. 2023')
ax.plot(requests, annane, marker='o', color='#ff7f0e', linewidth=1.8, label='Annane et al. 2022')
ax.plot(requests, blockchain_cpabe, marker='o', color='#d62728', linewidth=1.8, label='Blockchain CP-ABE')
ax.plot(requests, myeong, marker='o', color='#e377c2', linewidth=1.8, label='Myeong et al. 2025')
ax.plot(requests, did_healthcare, marker='o', color='#9467bd', linewidth=1.8, label='DID-Based Healthcare')
ax.plot(requests, zkp_healthcare, marker='o', color='#8c564b', linewidth=1.8, label='ZKP-Based Healthcare')

# Highlight Proposed ZK-Cx-CP-ABE
ax.plot(requests, proposed, marker='o', color='#555555', linewidth=2.5, linestyle='-', label='Proposed ZK-Cx-CP-ABE')

ax.set_title('Scalability Comparison by Number of Access Requests', fontsize=12, fontweight='bold', pad=12)
ax.set_xlabel('Number of Access Requests', fontsize=11, fontweight='bold')
ax.set_ylabel('Average Response Time (ms)', fontsize=11, fontweight='bold')

ax.grid(True, linestyle='--', alpha=0.4)
ax.legend(loc='upper left', fontsize=9, ncol=2, framealpha=0.9)

plt.tight_layout()
plt.savefig('scalability_real_network_comparison.png', dpi=300)
plt.show()