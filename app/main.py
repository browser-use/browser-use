from app.agent import run_browser_task


def main():
	task = input('Enter your browser task: ').strip()

	if not task:
		print('Task cannot be empty.')
		return

	run_browser_task(task)


if __name__ == '__main__':
	main()
