import time
import os
import logging
import traceback
import shutil
import uuid
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from db_utils import DBHandler
from driver_utils import get_driver
import pikepdf
from dotenv import load_dotenv

load_dotenv()

# Configuration (secrets are loaded from .env - see .env.example)
DB_CONFIG = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', '5432'))
}

PORTAL_URL = os.getenv('PORTAL_URL', "https://www.eye2serve.com/TP2.0/#/login")

# Branch-specific Credentials
CREDENTIALS = {
    "Arakkonam": {"user": os.getenv('ARAKKONAM_USER'), "pass": os.getenv('ARAKKONAM_PASS')},
    "Tadapatri": {"user": os.getenv('TADAPATRI_USER'), "pass": os.getenv('TADAPATRI_PASS')},
}

# Fallback/Default if branch is unknown
DEFAULT_USER = os.getenv('DEFAULT_USER')
DEFAULT_PASS = os.getenv('DEFAULT_PASS')

BASE_DIR = os.getenv('BASE_DIR', r"C:\Users\kaviy\Downloads\wbai_doc_extractor_engine-maincopy\wbai_doc_extractor_engine-maincopy")

SELECTORS = {
    "user_input": "//input[@placeholder='User Name' or @type='text']",
    "pass_input": "//input[@placeholder='Password' or @type='password']",
    "login_btn": "//button[contains(normalize-space(.), 'Login') or @type='submit']",
    "later_btn": "//button[contains(normalize-space(.), 'Later')]",
    "bill_submission": "//a[contains(normalize-space(.), 'Bill Submission')]",
    "epod_n": "//a[contains(normalize-space(.), 'EPOD N') and not(contains(normalize-space(.), 'File'))]", 
    "epod_n_upload": "//a[contains(normalize-space(.), 'EPOD N File upload')]",
    "search_input": "input[type='search']",
    "seal_invoice_upload": "td:nth-child(10) label, td:nth-child(10) div",
    "lr_copy_upload": "td:nth-child(11) label, td:nth-child(11) div",
    "weighment_slip_upload": "td:nth-child(12) label, td:nth-child(12) div",
    "row_submit_btn": "td:nth-child(15) button",
    "warning_ok": "//button[contains(text(), 'OK')]"
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def find_element_robust(driver, selector, wait=None):
    by = By.XPATH if selector.startswith("//") or selector.startswith("(") else By.CSS_SELECTOR
    if wait:
        return wait.until(EC.visibility_of_element_located((by, selector)))
    return driver.find_element(by, selector)

def resolve_path(db_path):
    if not db_path: return None
    parts = db_path.split('\\')
    clean_path = '\\'.join(parts[parts.index('split_pdfs'):]) if 'split_pdfs' in parts else db_path.split('\\')[-1]
    full_path = os.path.join(BASE_DIR, clean_path)
    if os.path.exists(full_path): return full_path
    alt = os.path.join(os.path.dirname(BASE_DIR), db_path)
    return alt if os.path.exists(alt) else None

def compress_pdf(input_path, output_path, branch=None, target_kb=100):
    """Compress PDF to under target_kb (default 100 KB).
    Uses branch‑aware settings: Tadapatri gets higher‑quality Ghostscript and PIL profiles.
    """
    TARGET_KB = target_kb

    try:
        orig_size_kb = os.path.getsize(input_path) / 1024
        logger.info(f"Original size before compression: {orig_size_kb:.2f} KB (File: {os.path.basename(input_path)})")
    except Exception as e:
        logger.warning(f"Could not get original size: {e}")

    # Stage 1: Try Ghostscript (best compression, reduces image DPI but keeps vectors)
    try:
        import subprocess
        gs_profiles = [
            # High‑quality color (printer quality, larger file)
            ["-dPDFSETTINGS=/printer"],
            # Color decent quality (ebook, ~150 dpi)
            ["-dPDFSETTINGS=/ebook"],
            # Low‑quality grayscale (screen, ~72 dpi) – fallback
            ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray", "-dPDFSETTINGS=/screen"],
        ]
        # If branch is not Tadapatri, prioritize smaller size first
        if branch != "Tadapatri":
            gs_profiles = list(reversed(gs_profiles))

        for profile in gs_profiles:
            cmd = ["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dNOPAUSE", "-dQUIET", "-dBATCH"] + profile + [f"-sOutputFile={output_path}", input_path]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(output_path):
                size_kb = os.path.getsize(output_path) / 1024
                logger.info(f"Ghostscript size: {size_kb:.2f} KB | Profile: {profile[-1]}")
                if size_kb <= TARGET_KB:
                    return output_path
                    
        logger.warning(f"Ghostscript couldn't hit {TARGET_KB}KB. Trying PIL Grayscale...")
    except Exception as e:
        logger.warning(f"Ghostscript failed: {e}. Trying PIL...")

    # Stage 2: Render each page as image iteratively using pdf2image + Pillow
    try:
        from pdf2image import convert_from_path
        from PIL import Image
        import io, pikepdf

        # Branch‑aware image handling: preserve color for Tadapatri, grayscale otherwise
        if branch == "Tadapatri":
            # Use color conversion and higher quality settings
            conversion = "RGB"
            pil_quality_pairs = [(150, 80), (120, 70), (100, 60), (72, 50)]
        else:
            # Grayscale conversion (default) with lower quality settings
            conversion = "L"
            pil_quality_pairs = [(150, 70), (100, 60), (72, 50), (60, 40), (50, 30), (40, 20), (30, 15), (20, 10), (15, 5)]
        for dpi, qual in pil_quality_pairs:
            pages = convert_from_path(input_path, dpi=dpi)
            img_list = []
            for page in pages:
                buf = io.BytesIO()
                page.convert(conversion).save(buf, format="JPEG", quality=qual, optimize=True)
                buf.seek(0)
                img_list.append(Image.open(buf).copy())

            if img_list:
                img_list[0].save(
                    output_path, save_all=True, append_images=img_list[1:],
                    format="PDF", optimize=True
                )
                size_kb = os.path.getsize(output_path) / 1024
                logger.info(f"Compressed size (PIL Gray dpi={dpi} q={qual}): {size_kb:.2f} KB")
                if size_kb <= TARGET_KB:
                    return output_path
                    
        # If the lowest setting still isn't enough, we just proceed with what we have
    except Exception as e:
        logger.warning(f"PIL compression failed: {e}. Trying pikepdf...")

    # Stage 3: pikepdf fallback
    try:
        with pikepdf.open(input_path) as pdf:
            pdf.save(output_path, linearize=True)
        size_kb = os.path.getsize(output_path) / 1024
        logger.info(f"Compressed size (pikepdf): {size_kb:.2f} KB")
        return output_path
    except Exception as e:
        logger.error(f"All compression failed: {e}. Using original.")
        shutil.copy2(input_path, output_path)
        return output_path


def get_16_char_path(original_path, row_id, file_type, di_no, attempt=12):
    """Creates a temporary copy, compresses it, and sets 12-char base name (16 total)."""
    temp_dir = os.path.join(os.getcwd(), "temp_uploads")
    if not os.path.exists(temp_dir): os.makedirs(temp_dir)
    
    # Try 12 characters for base name (base + .pdf = 16 total)
    type_code = file_type[0].upper() # S, L, W
    base = f"{di_no}{type_code}{row_id}"
    clean_name = "".join(c for c in base if c.isalnum()).upper()
    final_name = clean_name[:attempt].ljust(attempt, '0')
    
    final_path = os.path.join(temp_dir, final_name + ".pdf")
    compress_pdf(original_path, final_path)
    
    return final_path

def automate_uploads():
    db = DBHandler(**DB_CONFIG)
    
    # Run in loop for server deployment
    while True:
        pending_rows = db.fetch_pending_uploads()
        if not pending_rows:
            logger.info("No pending rows. Waiting 3 minutes...")
            time.sleep(180)
            continue

        # Group rows by branch
        rows_by_branch = {}
        for row in pending_rows:
            br = row.get('branch') or "Arakkonam" # Default to Arakkonam if not specified
            if br not in rows_by_branch: rows_by_branch[br] = []
            rows_by_branch[br].append(row)

        for branch, branch_rows in rows_by_branch.items():
            logger.info(f"Processing {len(branch_rows)} rows for branch: {branch}")
            
            # Headless=True for Server, set False for local debugging
            driver = get_driver(headless=True)
            wait = WebDriverWait(driver, 30)
            
            try:
                driver.get(PORTAL_URL)
                logger.info(f"Page loaded for {branch}.")
                
                # Login for this specific branch
                creds = CREDENTIALS.get(branch)
                if not creds:
                    logger.error(f"No credentials found for branch: {branch}. Skipping.")
                    continue
                
                logger.info(f"Logging in for branch: {branch} using user {creds['user']}")
                
                find_element_robust(driver, SELECTORS["user_input"], wait).send_keys(creds['user'])
                find_element_robust(driver, SELECTORS["pass_input"]).send_keys(creds['pass'])
                
                # Robust click for login
                login_btn = find_element_robust(driver, SELECTORS["login_btn"], wait)
                login_btn.click()
                logger.info(f"Login clicked for {branch}.")
                
                try:
                    later_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["later_btn"])))
                    later_btn.click()
                    logger.info("Clicked Later.")
                except: logger.info("No Later button.")

                def nav_click(selector, label):
                    by = By.XPATH if selector.startswith("//") or selector.startswith("(") else By.CSS_SELECTOR
                    elem = wait.until(EC.presence_of_element_located((by, selector)))
                    if elem.is_displayed(): ActionChains(driver).move_to_element(elem).perform()
                    driver.execute_script("arguments[0].click();", elem)
                    logger.info(f"Clicked {label}.")
                    time.sleep(2)

                nav_click(SELECTORS["bill_submission"], "Bill Submission")
                nav_click(SELECTORS["epod_n"], "EPOD N")
                nav_click(SELECTORS["epod_n_upload"], "EPOD N File upload")
                
                logger.info("Reached upload section.")
                
                for row in branch_rows:
                    temp_files = []
                    row_failed = False
                    try:
                        row_id, di_no = row['id'], row['di_no']
                        raw_paths = {"seal": resolve_path(row['seal_invoice']), "lr": resolve_path(row['lr_copy']), "ws": resolve_path(row['weighment_slip'])}
                        
                        available_paths = {k: v for k, v in raw_paths.items() if v}
                        if not available_paths:
                            logger.warning(f"Row {row_id} has NO valid files. Skipping.")
                            continue

                        # Simple name mapping for testing as requested by user
                        name_map = {"seal": "1", "lr": "2", "ws": "3"}
                        paths = {}
                        for k, v in available_paths.items():
                            temp_dir = os.path.join(os.getcwd(), "temp_uploads")
                            if not os.path.exists(temp_dir): os.makedirs(temp_dir)
                            fpath = os.path.join(temp_dir, f"{name_map[k]}.pdf")
                            
                            # Pass the current branch to preserve color for Tadapatri
                            compress_pdf(v, fpath, branch=branch)
                            paths[k] = fpath

                        temp_files = list(paths.values())
                        expected_count = len(paths)
                        success_count = 0

                        logger.info(f"Processing Row {row_id}, DI: {di_no}. Expected uploads: {expected_count}")
                        search = find_element_robust(driver, SELECTORS["search_input"], wait)
                        search.click()
                        search.clear()
                        search.send_keys(di_no)
                        search.send_keys(Keys.ENTER)
                        time.sleep(5) 
                        
                        # Find the specific row for this DI
                        try:
                            row_xpath = f"//tr[contains(., '{di_no}')]"
                            result_row = wait.until(EC.presence_of_element_located((By.XPATH, row_xpath)))
                        except:
                            logger.error(f"Row for DI {di_no} not found after search.")
                            # If DI is not found in portal, it means it's already processed/uploaded.
                            db.mark_as_already_existed(row_id)
                            continue

                        # DYNAMIC COLUMN DETECTION (Find indices by header text)
                        header_indices = {}
                        headers = driver.find_elements(By.TAG_NAME, "th")
                        all_headers = [h.text.strip() for h in headers if h.text.strip()]
                        logger.info(f"Portal Headers Found: {all_headers}")

                        for i, th in enumerate(headers, 1):
                            txt = th.text.lower()
                            if "invoice" in txt: header_indices["seal"] = i
                            elif "lr" in txt: header_indices["lr"] = i
                            elif "weighment" in txt or "slip" in txt: header_indices["ws"] = i
                        
                        logger.info(f"Mapping Indices: {header_indices}")

                        for key in paths.keys():
                            try:
                                col_idx = header_indices.get(key)
                                if not col_idx:
                                    logger.error(f"Could not detect column for {key}")
                                    continue

                                # Find container within result_row at detected index
                                container_xpath = f"./td[{col_idx}]//label | ./td[{col_idx}]//div"
                                container = result_row.find_element(By.XPATH, container_xpath)
                                
                                f_input = None
                                for sq in ["./following-sibling::input[@type='file']", ".//input[@type='file']", "../input[@type='file']", "../../input[@type='file']"]:
                                    try:
                                        f_input = container.find_element(By.XPATH, sq)
                                        break
                                    except: continue
                                
                                if f_input:
                                    fname = os.path.basename(paths[key])
                                    f_input.send_keys(paths[key])
                                    time.sleep(2)
                                    
                                    # Check for immediate warning popup
                                    try:
                                        warning = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, SELECTORS["warning_ok"])))
                                        
                                        # TAKE SCREENSHOT OF THE WARNING POPUP
                                        ss_path = f"/root/podportalautomation/reject_{di_no}_{key}.png"
                                        try:
                                            driver.save_screenshot(ss_path)
                                            logger.info(f"Screenshot taken: {ss_path}")
                                        except Exception as e:
                                            logger.error(f"Could not take screenshot: {e}")

                                        # Log the actual warning message
                                        try:
                                            dialogs = driver.find_elements(By.XPATH, "//div[contains(@class,'dialog') or contains(@class,'modal-content') or @role='dialog']")
                                            if dialogs:
                                                warning_text = " | ".join([d.text.replace('\n', ' ') for d in dialogs])
                                            else:
                                                warning_text = warning.find_element(By.XPATH, "./ancestor::div[1]").text.replace('\n', ' ')
                                        except:
                                            warning_text = "(could not capture warning text)"
                                            
                                        warning.click()
                                        time.sleep(1)

                                        if key == "ws":
                                            # ws rejected = BAG type row, not mandatory — skip and continue
                                            logger.info(f"Row {row_id}: ws not required by portal (BAG type). Skipping ws. Portal says: {warning_text}")
                                            expected_count -= 1  # Reduce expected so mismatch check passes
                                        else:
                                            # seal or lr rejected = real problem, abort row
                                            logger.error(f"Portal rejected {key}: {fname} | Portal says: {warning_text}")
                                            row_failed = True
                                            break
                                    except:
                                        success_count += 1
                                        logger.info(f"Successfully uploaded {key}")
                                else:
                                    logger.error(f"Input not found for {key} at column {col_idx}")
                                    row_failed = True
                            except Exception as e:
                                logger.error(f"Upload fail for {key}: {e}")
                                row_failed = True

                        if row_failed or success_count != expected_count:
                            logger.warning(f"Row {row_id} ABORTED: Upload mismatch. Refreshing page for clean state...")
                            # Refresh and re-navigate to avoid corrupted portal state affecting next row
                            try:
                                driver.refresh()
                                time.sleep(3)
                                nav_click(SELECTORS["bill_submission"], "Bill Submission")
                                nav_click(SELECTORS["epod_n"], "EPOD N")
                                nav_click(SELECTORS["epod_n_upload"], "EPOD N File upload")
                                logger.info("Re-navigated to upload section after abort.")
                            except Exception as nav_err:
                                logger.error(f"Re-navigation failed: {nav_err}")
                            continue

                        logger.info(f"All {success_count} docs uploaded. Clicking submit...")
                        submit_btn = find_element_robust(driver, SELECTORS["row_submit_btn"], wait)
                        
                        # Scroll to button and ensure it's clickable
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
                        time.sleep(1)
                        
                        try:
                            # Standard click first
                            ActionChains(driver).move_to_element(submit_btn).click().perform()
                        except:
                            # Fallback to JS click
                            driver.execute_script("arguments[0].click();", submit_btn)
                        
                        # Wait for Success Confirmation (Toast or Popup) - up to 60 seconds for slow portal
                        submit_success = False
                        try:
                            success_msg = WebDriverWait(driver, 60).until(
                                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Success') or contains(text(), 'uploaded successfully') or contains(text(), 'Successfully') or contains(text(), 'record updated')]"))
                            )
                            logger.info(f"Row {row_id} confirmed success: {success_msg.text}")
                            db.update_status_to_false(row_id)
                            submit_success = True
                        except:
                            # Alternative check: if the DI row disappeared from table = portal removed it after success
                            logger.warning(f"Row {row_id}: No toast message. Checking if row disappeared from table...")
                            try:
                                time.sleep(3)
                                gone = True
                                try:
                                    WebDriverWait(driver, 5).until(
                                        EC.presence_of_element_located((By.XPATH, f"//tr[contains(., '{di_no}')]"))
                                    )
                                    gone = False
                                except:
                                    gone = True  # Row not found = it was removed = success!

                                if gone:
                                    logger.info(f"Row {row_id} SUCCESS (row removed from table after submit).")
                                    db.update_status_to_false(row_id)
                                    submit_success = True
                                else:
                                    logger.error(f"Row {row_id} SUBMIT FAILURE: Row still in table. Taking screenshot...")
                                    db.mark_as_failed(row_id)
                                    ss_path = f"/root/podportalautomation/submit_fail_{row_id}.png"
                                    driver.save_screenshot(ss_path)
                                    logger.error(f"Screenshot saved: {ss_path}")
                                    # Refresh to clean state for next row
                                    driver.refresh()
                                    time.sleep(3)
                                    nav_click(SELECTORS["bill_submission"], "Bill Submission")
                                    nav_click(SELECTORS["epod_n"], "EPOD N")
                                    nav_click(SELECTORS["epod_n_upload"], "EPOD N File upload")
                            except Exception as alt_err:
                                logger.error(f"Row {row_id} SUBMIT FAILURE: Alt check failed: {alt_err}")
                                db.mark_as_failed(row_id)

                        time.sleep(2)

                        try:
                            warning = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.XPATH, SELECTORS["warning_ok"])))
                            warning.click()
                            time.sleep(1)
                        except: pass
                                
                    except Exception:
                        logger.error(f"Row {row_id} failed: {traceback.format_exc()}")
                    finally:
                        for f in temp_files:
                            try: os.remove(f)
                            except: pass

            except Exception as e:
                logger.error(f"Critical error for branch {branch}: {traceback.format_exc()}")
            finally:
                try: driver.quit()
                except: pass
        
        if os.path.exists("temp_uploads"): shutil.rmtree("temp_uploads", ignore_errors=True)
        logger.info("Cycle finished. Waiting 3 minutes next check...")
        time.sleep(180)

if __name__ == "__main__":
    automate_uploads()
