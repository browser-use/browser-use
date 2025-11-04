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

# Convert to tasks completed with $1
# Note: cost_per_task is in cents, so convert to dollars first
data = {}
budget = 1  # dollars
for model, info in data_raw.items():
	cost_per_task_dollars = info['cost_per_task'] / 100  # convert cents to dollars
	tasks_with_budget = budget / cost_per_task_dollars
	data[model] = {'tasks_with_100': tasks_with_budget, 'score': info['score'], 'company': info['company']}

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
		tasks = [v['tasks_with_100'] for v in company_data.values()]
		scores = [v['score'] for v in company_data.values()]
		plt.scatter(tasks, scores, c=colors[company], s=150, label=company, edgecolors='none', alpha=0.8, zorder=3)

# Add labels for each point
for model, info in data.items():
	if model == 'BU 1.0':
		offset_x = 0
		offset_y = 2.5
		ha = 'center'
		label_text = 'BU 1.0 ★'
	elif model == 'Claude Sonnet 4.5':
		offset_x = 7.5
		offset_y = 0
		ha = 'center'
		label_text = model
	elif model == 'Gemini 2.5 Pro':
		offset_x = 0
		offset_y = -2
		ha = 'center'
		label_text = model
	elif model == 'GPT-5-mini':
		offset_x = 0
		offset_y = -2
		ha = 'center'
		label_text = model
	elif model == 'GPT-5':
		offset_x = 0
		offset_y = 2
		ha = 'center'
		label_text = model
	elif model == 'GPT-4.1-mini':
		offset_x = 0
		offset_y = -2
		ha = 'center'
		label_text = model
	elif model == 'GPT-4o':
		offset_x = 0
		offset_y = -2
		ha = 'center'
		label_text = model
	elif model == 'Gemini-Flash-Latest':
		offset_x = 0
		offset_y = 2
		ha = 'center'
		label_text = model
	else:
		offset_x = 0
		offset_y = 2.5
		ha = 'center'
		label_text = model

	plt.text(
		info['tasks_with_100'] + offset_x,
		info['score'] + offset_y,
		label_text,
		fontsize=14,
		color='white',
		ha=ha,
		va='center',
		fontweight='bold',
	)

# Draw dashed lines connecting pareto frontier (upper-right is optimal: high tasks, high score)
pareto_points = [
	('BU 1.0', 'Claude Sonnet 4.5'),
]

for p1, p2 in pareto_points:
	x = [data[p1]['tasks_with_100'], data[p2]['tasks_with_100']]
	y = [data[p1]['score'], data[p2]['score']]
	plt.plot(x, y, 'k--', linewidth=1, alpha=0.5, zorder=1)

# Styling
plt.xlabel('Tasks Completed with $1', fontsize=12, color='white')
plt.ylabel('Accuracy', fontsize=12, color='white')
plt.title('Performance on WebBench-200', fontsize=14, color='white', pad=20)

# Set axis limits - calculate based on data range
max_tasks = max(v['tasks_with_100'] for v in data.values())
plt.xlim(0, max_tasks * 1.1)
plt.ylim(60, 90)

# Grid
plt.grid(True, linestyle='--', alpha=0.3, color='gray')

# Legend
plt.legend(loc='lower left', ncol=2, framealpha=0.9, facecolor='black', edgecolor='white', fontsize=10, labelcolor='white')

# Tick colors
ax.tick_params(colors='white', which='both')
for spine in ax.spines.values():
	spine.set_color('white')

plt.tight_layout()
plt.savefig('webbench_performance_cost.png', dpi=300, facecolor='black')
plt.close()
