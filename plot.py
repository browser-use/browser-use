import matplotlib.pyplot as plt

# Data points from the chart (time in seconds per task)
data_raw = {
	'Gemini 2.5 Pro': {'time_seconds': 95, 'score': 78.7, 'company': 'Google', 'cost_per_task': 14.7},
	'GPT-5': {'time_seconds': 199, 'score': 81.0, 'company': 'OpenAI', 'cost_per_task': 25.4},
	'GPT-5-mini': {'time_seconds': 164, 'score': 79.0, 'company': 'OpenAI', 'cost_per_task': 4.9},
	'Claude Sonnet 4.5': {'time_seconds': 186, 'score': 86.4, 'company': 'Anthropic', 'cost_per_task': 39.2},
	'GPT-4.1-mini': {'time_seconds': 105, 'score': 72.8, 'company': 'OpenAI', 'cost_per_task': 4.8},
	'BU 1.0': {'time_seconds': 33.4, 'score': 82.0, 'company': 'Browser-Use', 'cost_per_task': 1.6},
	'GPT-4o': {'time_seconds': 123, 'score': 71.8, 'company': 'OpenAI', 'cost_per_task': 39.2},
	'Gemini-Flash-Latest': {'time_seconds': 97, 'score': 80.2, 'company': 'Google', 'cost_per_task': 5.5},
}

# bu local 15,495,235 total tokens
# 14,991,649 input * 0.5 = 7,495,824.5
# 503,586 output * 3 = 1,510,758
# 7,495,824.5 + 1,510,758 = 9,006,582.5
# 9,006,582.5 / 198 = 45,487.7899

# bu local option 2 15,495,235 total tokens
# 14,991,649 input  - 5,200,000 cached = 9,791,649 input
#
# 9,791,649 * 0.2 = 1,958,329.8
# 5200000 * 0.02 = 104,000
# 1,958,329.8 + 104,000 = 2,062,329.8
# 503,586 output * 2 = 1,007,172

# 2,062,329.8 + 1,007,172 = 3,069,501.8
# 3,069,501.8 / 198 = 15,497.483838383838


# 15.000.000 / 198 = 75,757.57575757576
# 75,757.57575757576 / 13 = 5,827.505827505827
# 2000 * 200 = 400,000
# 400,000 * 13 = 5,200,000


# gemini-latest flash
# 23,747,279
# 21,330,751 input
# 2,416,528 output


# Convert to tasks per hour (speed)
data = {}
for model, info in data_raw.items():
	tasks_per_hour = 3600 / info['time_seconds']
	data[model] = {'speed': tasks_per_hour, 'score': info['score'], 'company': info['company']}

# Company colors
colors = {
	'OpenAI': '#3498db',  # bright blue
	'Anthropic': '#e74c3c',  # bright red
	'Google': '#9b59b6',  # purple
	'Browser-Use': '#2ecc71',  # bright green
}

# Create figure with dark background
plt.figure(figsize=(12, 6))
ax = plt.gca()
ax.set_facecolor('black')
plt.gcf().patch.set_facecolor('black')

# Plot points by company
for company in ['OpenAI', 'Anthropic', 'Google', 'Browser-Use']:
	company_data = {k: v for k, v in data.items() if v['company'] == company}
	if company_data:
		speeds = [v['speed'] for v in company_data.values()]
		scores = [v['score'] for v in company_data.values()]
		plt.scatter(speeds, scores, c=colors[company], s=150, label=company, edgecolors='none', alpha=0.8, zorder=3)

# Add labels for each point
for model, info in data.items():
	if model == 'BU 1.0':
		offset_x = 0
		offset_y = 2.5
		ha = 'center'
		label_text = 'BU 1.0 ★'
	elif model == 'Claude Sonnet 4.5':
		offset_x = 13.5
		offset_y = 0
		ha = 'center'
		label_text = model
	elif model == 'Gemini 2.5 Pro':
		offset_x = 11
		offset_y = -1
		ha = 'center'
		label_text = model
	elif model == 'GPT-5-mini':
		offset_x = 5
		offset_y = 1.3
		ha = 'center'
		label_text = model
	elif model == 'GPT-5':
		offset_x = 0
		offset_y = 2
		ha = 'center'
		label_text = model
	elif model == 'GPT-4.1-mini':
		offset_x = 10
		offset_y = 0
		ha = 'center'
		label_text = model
	elif model == 'GPT-4o':
		offset_x = 0
		offset_y = -2.5
		ha = 'center'
		label_text = model
	elif model == 'Gemini-Flash-Latest':
		offset_x = 13
		offset_y = 1.5
		ha = 'center'
		label_text = model
	else:
		offset_x = 0
		offset_y = 2.5
		ha = 'center'
		label_text = model

	plt.text(
		info['speed'] + offset_x,
		info['score'] + offset_y,
		label_text,
		fontsize=14,
		color='white',
		ha=ha,
		va='center',
		fontweight='bold',
	)

# Draw dashed lines connecting pareto frontier (upper-right is optimal: high speed, high score)
pareto_points = [
	('Claude Sonnet 4.5', 'BU 1.0'),
]

for p1, p2 in pareto_points:
	x = [data[p1]['speed'], data[p2]['speed']]
	y = [data[p1]['score'], data[p2]['score']]
	plt.plot(x, y, 'k--', linewidth=1, alpha=0.5, zorder=1)

# Styling
plt.xlabel('Tasks Completed Per Hour', fontsize=14, color='white', fontweight='bold')
plt.ylabel('Accuracy', fontsize=14, color='white', fontweight='bold')
plt.title('Performance on WebBench-200', fontsize=14, color='white', pad=20)

# Set axis limits
plt.xlim(0, 120)
plt.ylim(60, 90)

# Grid
plt.grid(True, linestyle='--', alpha=0.3, color='gray')

# Legend
plt.legend(loc='lower left', ncol=2, framealpha=0.9, facecolor='black', edgecolor='white', fontsize=10, labelcolor='white')

# Tick colors
ax.tick_params(colors='white', which='both')
for spine in ax.spines.values():
	spine.set_color('white')

# Make tick labels bold
for label in ax.get_xticklabels():
	label.set_fontweight('bold')
for label in ax.get_yticklabels():
	label.set_fontweight('bold')

plt.tight_layout()
plt.savefig('webbench_performance.png', dpi=300, facecolor='black')
plt.close()
