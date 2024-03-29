# import requests
# import asyncio
# from typing import Dict, List, Optional
#
# from selenium.webdriver.support.wait import WebDriverWait
#
# from apps.scrapers.utils import catch_network
#
# BASE_URL = "https://www.pattersondental.com"
# session = requests.Session()
# LOGIN_HEADERS = {
#     "Accept": "application/json, text/javascript, */*; q=0.01",
#     "Accept-Language": "en-US,en;q=0.9",
#     "Connection": "keep-alive",
#     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
#     "Origin": "https://pattersonb2c.b2clogin.com",
#     "Sec-Fetch-Dest": "empty",
#     "Sec-Fetch-Mode": "cors",
#     "Sec-Fetch-Site": "same-origin",
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#                   "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
#     "X-Requested-With": "XMLHttpRequest",
#     "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
#     "sec-ch-ua-mobile": "?0",
#     "sec-ch-ua-platform": '"Windows"',
# }
#
# HOME_HEADERS = {
#     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
#               "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
#     "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
#     "Cache-Control": "max-age=0",
#     "Connection": "keep-alive",
#     "Sec-Fetch-Dest": "document",
#     "Sec-Fetch-Mode": "navigate",
#     "Sec-Fetch-Site": "none",
#     "Sec-Fetch-User": "?1",
#     "Upgrade-Insecure-Requests": "1",
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
#                   "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
#     "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
#     "sec-ch-ua-mobile": "?0",
#     "sec-ch-ua-platform": '"Windows"',
# }
#
#
# def gen_options(headless=True):
#     language = "en-US"
#     user_agent = (
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
#         "Chrome/120.0.0.0 Safari/537.36"
#     )
#
#     chrome_options = webdriver.ChromeOptions()
#     chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
#     chrome_options.add_argument("--disable-logging")
#     chrome_options.add_argument("--log-level=3")
#     chrome_options.add_argument("--disable-infobars")
#     chrome_options.add_argument("--disable-extensions")
#     chrome_options.add_argument("--window-size=1366,768")
#     chrome_options.add_argument("--lang=en-US,en;q=0.9")
#     chrome_options.add_argument("--disable-notifications")
#     chrome_options.add_argument(f"--user-agent={user_agent}")
#     chrome_options.add_argument(f"--lang={language}")
#     chrome_options.add_argument("--mute-audio")
#     chrome_options.add_argument("--disable-dev-shm-usage")
#     if headless:
#         chrome_options.add_argument("--headless=new")
#     chrome_options.add_argument("--window-size=1366,768")
#     chrome_options.add_experimental_option(
#         "prefs",
#         {
#             "profile.default_content_setting_values.notifications": 2,
#         },
#     )
#     return chrome_options
#
# def setup_driver( headless=True):
#     chrome_options =  gen_options(headless=headless)
#     driver = webdriver.Chrome(
#         options=chrome_options,
#     )
#     # driver.set_window_size(1920, 1080)
#     return driver
#
#
# def get_home_page():
#     response = session.post(
#         url='https://realtime.oxylabs.io/v1/queries',
#         json={
#             'source': 'universal',
#             'url': BASE_URL,
#
#         },
#         auth=('Uzair123', 'Utor=1234567'),
#         timeout=20
#     )
#     print(f"Home Page: {response.text}")
#     return response
#
#
#
# def login_proc():
#      get_home_page()
#     account_page = f"{ BASE_URL}/Account"
#      driver.get(account_page)
#     email = WebDriverWait( driver, 10).until(EC.visibility_of_element_located((By.ID, "signInName")))
#     password =  driver.find_element(By.ID, "password")
#     email.send_keys( username)
#     password.send_keys( password)
#      driver.find_element(By.XPATH, '//button[@id="next"]').click()
#
#     try:
#         WebDriverWait( driver, 15).until(
#             EC.visibility_of_element_located((By.CLASS_NAME, "title-card__content"))
#         )
#     except Exception:
#         logger.debug("The credential is wrong")
#         raise errors.VendorAuthenticationFailed()
#
#     if not  check_authenticated():
#         logger.debug("Still not authenticated")
#         raise errors.VendorAuthenticationFailed()
#      set_cookies_from_driver()
#      driver.close()
#
#
#
# @catch_network
# async def login( username: Optional[str] = None, password: Optional[str] = None):
#     if username:
#            username = username
#     if password:
#            password = password
#
#     loop = asyncio.get_event_loop()
#     await loop.run_in_executor(None,    login_proc)
#     print("Login DONE")
#     return True
#
#
# get_home_page()
