import matplotlib.pyplot as plt
import numpy as np

# GAIA-Verified Browser Use Eval results
data = {
	'GPT-o3': {'score': 50.0, 'company': 'OpenAI'},
	'GPT-5.1 Thinking': {'score': 52.5, 'company': 'OpenAI'},
	'Claude Sonnet 4.5 Thinking': {'score': 54.6, 'company': 'Anthropic'},
	'Gemini 3.0 Pro': {'score': 68.2, 'company': 'Google'},
	'Gemini 3.0 Pro Thinking': {'score': 72.9, 'company': 'Google'},
}

# Sort by score (lowest to highest)
sorted_models = sorted(data.items(), key=lambda x: x[1]['score'])
models = [m[0] for m in sorted_models]
scores = [m[1]['score'] for m in sorted_models]
companies = [m[1]['company'] for m in sorted_models]

# Company colors (consistent with your other plots)
color_map = {
	'OpenAI': '#3498db',  # bright blue
	'Anthropic': '#e74c3c',  # bright red
	'Google': '#9b59b6',  # purple
}
colors = [color_map[c] for c in companies]

# Create figure with dark background
fig, ax = plt.subplots(figsize=(12, 7))
fig.patch.set_facecolor('black')
ax.set_facecolor('black')

# Create bar plot
bar_width = 0.6
x = np.arange(len(models))
bars = ax.bar(x, scores, bar_width, color=colors, edgecolor='white', linewidth=1.5, alpha=0.85)

# Add values on bars
for i, (bar, val) in enumerate(zip(bars, scores)):
	height = bar.get_height()
	ax.text(
		bar.get_x() + bar.get_width() / 2,
		height + 1.5,
		f'{val:.1f}%',
		ha='center',
		va='bottom',
		color='white',
		fontsize=18,
		fontweight='bold',
	)

# Styling
ax.set_xticks(x)
ax.set_xticklabels(models, fontsize=16, color='white', fontweight='bold', rotation=15, ha='right')
ax.set_ylabel('Accuracy (%)', fontsize=20, color='white', fontweight='bold')
ax.set_title('GAIA-Verified Browser Use Eval Results', fontsize=24, color='white', fontweight='bold', pad=20)
ax.set_ylim(30, 80)
ax.grid(True, linestyle='--', alpha=0.3, color='gray', axis='y')

# Tick colors
ax.tick_params(colors='white', which='both')
for spine in ax.spines.values():
	spine.set_color('white')

# Make tick labels bold
for label in ax.get_xticklabels():
	label.set_fontweight('bold')

# Add legend
from matplotlib.patches import Patch

legend_elements = [Patch(facecolor=color_map[c], edgecolor='white', label=c) for c in ['OpenAI', 'Anthropic', 'Google']]
ax.legend(
	handles=legend_elements,
	loc='lower right',
	framealpha=0.9,
	facecolor='black',
	edgecolor='white',
	fontsize=14,
	labelcolor='white',
)

plt.tight_layout()
plt.savefig('gaia_eval_results.png', dpi=300, facecolor='black')
plt.close()

print('GAIA eval results chart generated: gaia_eval_results.png')
