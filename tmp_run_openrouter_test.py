import importlib

def main():
    m = importlib.import_module('browser_use.tests.test_openrouter_extra_body')
    print('Imported', m)
    print('Running test_extra_body_forwarded...')
    m.test_extra_body_forwarded()
    print('Test completed')

if __name__ == '__main__':
    main()
