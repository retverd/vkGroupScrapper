from datetime import datetime
from json import loads
from os import getenv, makedirs
from os.path import join, exists
from re import compile, search
from time import sleep
from urllib.request import urlretrieve

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement

# Waiting for lightweight page load
TINY_TIMEOUT = 1
SHORT_TIMEOUT = 3

DATE_TIME_FORMAT_FOR_FILES = "%Y_%m_%d_%H_%M_%S"
ATTACH_ON_CLICK_PATTERN = compile(r'({\"temp\":{.*}), event\)')


def get_env_strict(key: str) -> str:
    value = getenv(key)
    if value is None:
        raise AttributeError(f"Mandatory environment variable {key} is not set or empty!")
    return value


def setup_driver() -> WebDriver:
    options = Options()
    options.add_experimental_option("prefs", {
        "download.default_directory": file_path,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    })
    options.add_argument("--disable-extensions")  # disabling extensions
    options.add_argument(f"--user-data-dir={path_to_user_profile}")  # turn on profile
    # options.add_argument('--headless')
    options.add_argument('--start-maximized')
    options.add_argument("--no-sandbox")  # Bypass OS security model

    s = Service(path_to_exec)

    # PyCharm doesn't like this string, but it is correct!
    return webdriver.Chrome(options=options, service=s)


def vk_login(loc_driver: WebDriver):
    # Check if already logged in
    if not loc_driver.find_elements(By.ID, "top_profile_link"):
        print("Not logged in! Login required!")
        if loc_driver.find_elements(By.ID, "quick_email"):
            # Login form is displayed, let's try to get in!
            ac = loc_driver.find_element(value="quick_email")
            ac.send_keys(username)

            ac = loc_driver.find_element(value="quick_pass")
            ac.send_keys(password)

            ac = loc_driver.find_element(value="quick_login_button")
            ac.send_keys(Keys.ENTER)
            sleep(SHORT_TIMEOUT)

            while not loc_driver.find_elements(By.ID, "top_profile_link"):
                # TODO: Retest this block!
                if loc_driver.find_elements(By.ID, "submit_post_box"):
                    # Captcha detected!
                    captcha_code = input("Provide captcha code to proceed: ")
                    ac = loc_driver.find_element(value="authcheck_code")  # FIXME
                    ac.send_keys(captcha_code + Keys.ENTER)
                elif loc_driver.find_elements(By.ID, "authcheck_code"):
                    # Auth code is required!
                    auth_code = input("Provide auth code to proceed: ")
                    ac = loc_driver.find_element(value="authcheck_code")
                    ac.send_keys(auth_code + Keys.ENTER)
                else:
                    # Something unexpected happened!
                    body: WebElement = loc_driver.find_element(By.TAG_NAME, "body")
                    body.screenshot(
                        join(file_path, f'login_failed_{datetime.now().strftime(DATE_TIME_FORMAT_FOR_FILES)}.png'))
                    raise RuntimeError("Login failed, something went wrong!")
        else:
            body: WebElement = loc_driver.find_element(By.TAG_NAME, "body")
            body.screenshot(
                join(file_path, f'login_form_not_shown_{datetime.now().strftime(DATE_TIME_FORMAT_FOR_FILES)}.png'))
            raise RuntimeError("Login form is now shown, something went wrong!")


def vk_capture_posts(loc_driver: WebDriver) -> None:
    # Get num of last processed post
    with open('last_post.num', 'r') as file_reader:
        last_prev_post_num = int(file_reader.read())

    # Preparations
    main_window = loc_driver.current_window_handle
    processed_posts = []
    have_posts_to_process = True

    while have_posts_to_process:
        # Get all visible posts
        all_visible_wall_posts = loc_driver.find_elements(By.CLASS_NAME, value="post")
        print(f"Found {len(all_visible_wall_posts)} posts. Going through!")

        # Iterate over all found posts and save them to disk
        for post in all_visible_wall_posts:  # type: WebElement
            try:
                cur_post_id: str = post.get_attribute("id")
            except StaleElementReferenceException:
                print("Element is not accessible, need to scroll page down!")
                break

            cur_post_num = int(cur_post_id[cur_post_id.rfind('_') + 1:])

            # Check if this post was already processed
            if cur_post_num not in processed_posts:
                # Remember last post num during this session to skip this and earlier posts next time
                if cur_post_num > last_prev_post_num:

                    # Create new folder if required
                    tgt_folder = join(file_path, cur_post_id)
                    if not exists(tgt_folder):
                        makedirs(tgt_folder)

                    # Open current post in new tab and switch to it
                    post.find_element(By.XPATH, ".//a[@class='post_link']").send_keys(Keys.CONTROL + Keys.RETURN)
                    loc_driver.switch_to.window(loc_driver.window_handles[1])

                    # Screenshot post
                    post_text = loc_driver.find_element(By.XPATH, ".//div[@class='_post_content']")
                    total_height = post_text.size["height"]  # + 1000
                    loc_driver.set_window_size(1920, total_height)
                    sleep(TINY_TIMEOUT)
                    post_text.screenshot(join(tgt_folder, f'_{cur_post_id}.png'))
                    sleep(TINY_TIMEOUT)
                    # Save all attachments
                    i = 1
                    for attach in post_text.find_elements(By.XPATH,
                                                          value="div[contains(@class,'wall_post_cont')]/"
                                                                "div[contains(@class,'page_post_sized_thumbs')]/"
                                                                "a[contains(@class,'page_post_thumb_wrap')]"):  # type: WebElement

                        # Extract image URL
                        attach_on_click = attach.get_attribute('onclick')
                        m = search(ATTACH_ON_CLICK_PATTERN, attach_on_click)
                        if m:
                            img_url_block = loads(m.group(1))['temp']
                        else:
                            raise RuntimeError(f"Was unable to find onclick content "
                                               f"for link with id = '{attach.get_attribute('data-photo-id')}'")

                        if 'z' in img_url_block:
                            urlretrieve(img_url_block['z'], join(tgt_folder, "img_z_{:02}.jpg".format(i)))
                        else:
                            urlretrieve(img_url_block['x'], join(tgt_folder, "img_x_{:02}.jpg".format(i)))

                        i += 1

                    # Add post num to the list of processed posts to avoid it in future
                    processed_posts.append(cur_post_num)

                    # Close tab and return to the group wall
                    loc_driver.close()
                    loc_driver.switch_to.window(main_window)

                else:
                    have_posts_to_process = False
                    break

        if have_posts_to_process:
            # Scroll to the bottom to get more posts and come back
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    if not processed_posts:
        print("Nothing to capture! :)")
    else:
        # Save last post num to env variable
        with open('last_post.num', 'w') as file_writer:
            file_writer.write(str(max(processed_posts)))


if __name__ == '__main__':
    # Get all required values
    path_to_user_profile = get_env_strict("CHROME_PROFILE_PATH")
    path_to_exec = get_env_strict("CHROME_WEBDRIVER_PATH")
    file_path = get_env_strict("SAVE_TO_PATH")
    username = get_env_strict("VK_USER")
    password = get_env_strict("VK_PASS")
    group_link = get_env_strict("VK_GROUP_LINK")

    # Setup driver
    driver = setup_driver()

    # Open group page
    driver.get(group_link)
    sleep(SHORT_TIMEOUT)

    # Log in if required
    vk_login(driver)

    # Capture all posts and update file with mark
    vk_capture_posts(driver)

    input("All posts are captured! Please hit Enter to exit...")
    driver.quit()
