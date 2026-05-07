#!/usr/bin/env python3
import os
import sys
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from shutil import copyfile

try:
    from wand.image import Image
except ImportError:
    print("ERROR: Wand/ImageMagick not available!")
    sys.exit(1)

from datetime import datetime, timezone
import uuid

BATCH_SIZE = 500
MAX_WORKERS = 16
RESOLUTIONS = [1, 2, 4]

THUMBNAIL_TYPE_COVER = 1
CACHE_TYPE_THUMBNAILS = 'thumbnails'


def get_config_from_db(app_db_path):
    conn = sqlite3.connect(app_db_path)
    c = conn.cursor()
    c.execute('SELECT config_calibre_dir FROM settings')
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_resize_height(resolution):
    return int(255 * resolution)


def get_resize_width(resolution, original_width, original_height):
    height = get_resize_height(resolution)
    percent = height / float(original_height)
    width = int(float(original_width) * percent)
    return width if width % 2 == 0 else width + 1


def get_cache_dir():
    return os.environ.get('CACHE_DIRECTORY',
                          os.environ.get('CACHE_DIR',
                                         os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cps', 'cache')))


def get_cache_file_path(filename, cache_type=None):
    cache_dir = get_cache_dir()
    if cache_type:
        cache_dir = os.path.join(cache_dir, cache_type)
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    subdir = os.path.join(cache_dir, filename[:2])
    if not os.path.isdir(subdir):
        os.makedirs(subdir, exist_ok=True)
    return os.path.join(subdir, filename)


def resize_cover(cover_filepath, resolution, output_path):
    if not os.path.isfile(cover_filepath):
        return False
    try:
        with Image(filename=cover_filepath) as img:
            height = get_resize_height(resolution)
            if img.height > height:
                width = get_resize_width(resolution, img.width, img.height)
                img.resize(width=width, height=height, filter='lanczos')
                img.format = 'jpeg'
                img.save(filename=output_path)
            else:
                copyfile(cover_filepath, output_path)
        return True
    except Exception as e:
        print(f'  ERROR resizing {cover_filepath}: {e}')
        return False


def main():
    app_db_path = os.environ.get('APP_DB_PATH', '/config/app.db')
    calibre_dir = get_config_from_db(app_db_path)
    if not calibre_dir:
        print(f"ERROR: Calibre library path not configured in {app_db_path}!")
        sys.exit(1)

    dbpath = os.path.join(calibre_dir, "metadata.db")
    if not os.path.isfile(dbpath):
        print(f"ERROR: Calibre database not found: {dbpath}")
        sys.exit(1)

    cache_dir = get_cache_dir()
    print(f"Calibre DB: {dbpath}")
    print(f"App DB: {app_db_path}")
    print(f"Book path: {calibre_dir}")
    print(f"Cache dir: {cache_dir}")
    print(f"Workers: {MAX_WORKERS}, Batch size: {BATCH_SIZE}")
    print(f"Resolutions: {RESOLUTIONS}")
    print()

    calibre_conn = sqlite3.connect(dbpath, check_same_thread=False)
    calibre_conn.row_factory = sqlite3.Row

    app_conn = sqlite3.connect(app_db_path, check_same_thread=False)
    app_conn.execute('PRAGMA journal_mode=WAL')
    app_conn.execute('PRAGMA synchronous=NORMAL')
    app_conn.execute('PRAGMA busy_timeout=30000')

    c_cur = calibre_conn.cursor()
    c_cur.execute('SELECT COUNT(*) FROM books WHERE has_cover=1')
    total = c_cur.fetchone()[0]
    print(f"Total books with covers: {total}")
    if total == 0:
        print("No books found!")
        sys.exit(0)

    a_cur = app_conn.cursor()
    a_cur.execute('SELECT entity_id, resolution, filename, generated_at FROM thumbnail WHERE type=1')
    existing = {}
    for row in a_cur.fetchall():
        key = (row[0], row[1])
        existing[key] = {'filename': row[2], 'generated_at': row[3]}
    print(f"Existing thumbnail records: {len(existing)}")
    print()

    start_time = time.time()
    total_generated = 0
    total_db_inserted = 0
    total_skipped = 0
    total_errors = 0
    offset = 0

    while True:
        c_cur.execute('SELECT id, path, last_modified FROM books WHERE has_cover=1 ORDER BY id LIMIT ? OFFSET ?',
                       (BATCH_SIZE, offset))
        books = c_cur.fetchall()
        if not books:
            break

        new_records = []
        work_items = []

        for book in books:
            book_id = book[0]
            book_path = book[1]
            last_modified = book[2]

            for resolution in RESOLUTIONS:
                key = (book_id, resolution)
                if key in existing:
                    thumb = existing[key]
                    cache_path = get_cache_file_path(thumb['filename'], CACHE_TYPE_THUMBNAILS)
                    need_update = False
                    if last_modified and thumb['generated_at']:
                        try:
                            lm = last_modified if isinstance(last_modified, str) else last_modified
                            ga = thumb['generated_at'] if isinstance(thumb['generated_at'], str) else thumb['generated_at']
                            if str(lm) > str(ga):
                                need_update = True
                        except Exception:
                            pass
                    if not os.path.isfile(cache_path):
                        need_update = True
                    if need_update:
                        cover_filepath = os.path.join(calibre_dir, book_path, 'cover.jpg')
                        work_items.append((cover_filepath, resolution, cache_path))
                    else:
                        total_skipped += 1
                else:
                    new_uuid = str(uuid.uuid4())
                    filename = f'{new_uuid}.jpg'
                    now = datetime.now(timezone.utc).isoformat()
                    new_records.append((book_id, new_uuid, 'jpeg', THUMBNAIL_TYPE_COVER, resolution, filename, now, None))
                    output_path = get_cache_file_path(filename, CACHE_TYPE_THUMBNAILS)
                    cover_filepath = os.path.join(calibre_dir, book_path, 'cover.jpg')
                    work_items.append((cover_filepath, resolution, output_path))

        if new_records:
            try:
                app_conn.executemany(
                    'INSERT INTO thumbnail (entity_id, uuid, format, type, resolution, filename, generated_at, expiration) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    new_records
                )
                app_conn.commit()
                total_db_inserted += len(new_records)
            except Exception as e:
                print(f'  DB INSERT ERROR: {e}')
                app_conn.rollback()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for cover_filepath, resolution, output_path in work_items:
                f = executor.submit(resize_cover, cover_filepath, resolution, output_path)
                futures[f] = cover_filepath

            for future in as_completed(futures):
                try:
                    if future.result():
                        total_generated += 1
                    else:
                        total_errors += 1
                except Exception:
                    total_errors += 1

        processed = offset + len(books)
        if processed % 5000 < BATCH_SIZE:
            elapsed = time.time() - start_time
            rate = total_generated / elapsed if elapsed > 0 else 0
            pct = processed / total * 100
            print(f'  Progress: {processed}/{total} books ({pct:.1f}%) - '
                  f'Generated: {total_generated}, DB inserted: {total_db_inserted}, '
                  f'Skipped: {total_skipped}, Errors: {total_errors}, Rate: {rate:.1f}/s')

        offset += BATCH_SIZE

    elapsed = time.time() - start_time
    rate = total_generated / elapsed if elapsed > 0 else 0
    print(f'\nDone in {elapsed:.1f}s!')
    print(f'  Books processed: {total}')
    print(f'  Thumbnails generated: {total_generated}')
    print(f'  DB records inserted: {total_db_inserted}')
    print(f'  Skipped (already cached): {total_skipped}')
    print(f'  Errors: {total_errors}')
    print(f'  Rate: {rate:.1f} thumbnails/s')

    calibre_conn.close()
    app_conn.close()


if __name__ == '__main__':
    main()
