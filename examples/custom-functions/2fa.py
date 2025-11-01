import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent

secret_key = os.environ.get('OTP_SECRET_KEY')
if not secret_key:
	# For this example copy the code from the website https://authenticationtest.com/totpChallenge/
	# For real 2fa just copy the secret key when you setup 2fa, you can get this e.g. in 1Password
	secret_key = 'JBSWY3DPEHPK3PXP'


sensitive_data = {'bu_2fa_code': secret_key}


task = """
1. Go to https://authenticationtest.com/totpChallenge/ and try to log in.
2. If prompted for 2FA code:
Input the the secret bu_2fa_code.

When you input bu_2fa_code, the 6 digit code will be generated automatically.
"""


Agent(task=task, sensitive_data=sensitive_data).run_sync()  # type: ignore
