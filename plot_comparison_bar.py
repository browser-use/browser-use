import matplotlib.pyplot as plt
import numpy as np

# Data for BU 1.0 and GPT-4o
data = {
	'BU 1.0': {'time_seconds': 33.4, 'score': 82.0, 'cost_per_task': 1.9},
	'GPT-4o': {'time_seconds': 123, 'score': 71.8, 'cost_per_task': 39.2},
}

# Prepare data for plotting (GPT-4o first, then BU 1.0)
models = ['GPT-4o', 'BU 1.0']
accuracy = [data[m]['score'] for m in models]
time_per_task = [data[m]['time_seconds'] for m in models]
cost_per_task = [data[m]['cost_per_task'] for m in models]

# Calculate ratios (relative to GPT-4o as baseline)
accuracy_ratio = accuracy[1] / accuracy[0]  # BU vs GPT-4o
time_speedup = time_per_task[0] / time_per_task[1]  # how much faster
cost_savings = cost_per_task[0] / cost_per_task[1]  # how much cheaper

# Colors
bu_color = '#ff8c00'  # orange
gpt_color = '#808080'  # grey

# Create figure with dark background
fig, axes = plt.subplots(1, 3, figsize=(13, 6))
fig.patch.set_facecolor('black')

# Bar width and positions
bar_width = 0.6
x = np.arange(2)

# === PLOT 1: Accuracy ===
ax1 = axes[0]
ax1.set_facecolor('black')
bars1 = ax1.bar(x, accuracy, bar_width, color=[gpt_color, bu_color], edgecolor='white', linewidth=1.5, alpha=0.85)
ax1.set_title('Accuracy on WebBench', fontsize=16, color='white', fontweight='bold', pad=15)
ax1.set_xticks(x)
ax1.set_xticklabels(models, fontsize=12, color='white', fontweight='bold')
ax1.set_ylim(65, 90)
ax1.grid(True, linestyle='--', alpha=0.3, color='gray', axis='y')
ax1.set_yticklabels([])

# Add values on bars
for i, (bar, val) in enumerate(zip(bars1, accuracy)):
	height = bar.get_height()
	ax1.text(
		bar.get_x() + bar.get_width() / 2,
		height + 0.7,
		f'{val:.1f}%',
		ha='center',
		va='bottom',
		color='white',
		fontsize=11,
		fontweight='bold',
	)
	if i == 1:  # BU 1.0
		ax1.text(
			bar.get_x() + bar.get_width() / 2,
			height + 2.5,
			'10.2% better',
			ha='center',
			va='bottom',
			color='#ff8c00',
			fontsize=13,
			fontweight='bold',
		)

# === PLOT 2: Time per Task (Speed) ===
ax2 = axes[1]
ax2.set_facecolor('black')
bars2 = ax2.bar(x, time_per_task, bar_width, color=[gpt_color, bu_color], edgecolor='white', linewidth=1.5, alpha=0.85)
ax2.set_title('Avg Time per Task', fontsize=16, color='white', fontweight='bold', pad=15)
ax2.set_xticks(x)
ax2.set_xticklabels(models, fontsize=12, color='white', fontweight='bold')
ax2.set_ylim(0, 140)
ax2.grid(True, linestyle='--', alpha=0.3, color='gray', axis='y')
ax2.set_yticklabels([])

# Add values and ratio on bars
for i, (bar, val) in enumerate(zip(bars2, time_per_task)):
	height = bar.get_height()
	ax2.text(
		bar.get_x() + bar.get_width() / 2,
		height + 3,
		f'{val:.1f}s',
		ha='center',
		va='bottom',
		color='white',
		fontsize=11,
		fontweight='bold',
	)
	if i == 1:  # BU 1.0
		ax2.text(
			bar.get_x() + bar.get_width() / 2,
			height + 15,
			f'{time_speedup:.1f}x faster',
			ha='center',
			va='bottom',
			color='#ff8c00',
			fontsize=13,
			fontweight='bold',
		)

# === PLOT 3: Cost per Task ===
ax3 = axes[2]
ax3.set_facecolor('black')
bars3 = ax3.bar(x, cost_per_task, bar_width, color=[gpt_color, bu_color], edgecolor='white', linewidth=1.5, alpha=0.85)
ax3.set_title('Avg Cost per Task', fontsize=16, color='white', fontweight='bold', pad=15)
ax3.set_xticks(x)
ax3.set_xticklabels(models, fontsize=12, color='white', fontweight='bold')
ax3.set_ylim(0, 45)
ax3.grid(True, linestyle='--', alpha=0.3, color='gray', axis='y')
ax3.set_yticklabels([])

# Add values and ratio on bars
for i, (bar, val) in enumerate(zip(bars3, cost_per_task)):
	height = bar.get_height()
	ax3.text(
		bar.get_x() + bar.get_width() / 2,
		height + 1,
		f'{val:.1f}¢',
		ha='center',
		va='bottom',
		color='white',
		fontsize=11,
		fontweight='bold',
	)
	if i == 1:  # BU 1.0
		ax3.text(
			bar.get_x() + bar.get_width() / 2,
			height + 6,
			f'{cost_savings:.0f}x cheaper',
			ha='center',
			va='bottom',
			color='#ff8c00',
			fontsize=13,
			fontweight='bold',
		)

# Style all axes
for ax in axes:
	ax.tick_params(colors='white', which='both')
	for spine in ax.spines.values():
		spine.set_color('white')
	# Make tick labels bold
	for label in ax.get_yticklabels():
		label.set_fontweight('bold')

# Add main title
fig.suptitle('Evolution of Browser Use in 2025', fontsize=22, color='white', fontweight='bold', y=0.96)

plt.tight_layout(rect=(0, 0, 1, 0.92))
plt.savefig('webbench_bu_vs_gpt4o.png', dpi=300, facecolor='black')
plt.close()

print('Bar chart comparison generated: webbench_bu_vs_gpt4o.png')
