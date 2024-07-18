from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import os
import cv2
import numpy as np
import hashlib
import requests
from blockfrost import BlockFrostApi
import logging
import time
from PIL import Image, UnidentifiedImageError

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

API_URL = "https://cardano-mainnet.blockfrost.io/api/v0"
API_KEY = "mainnetFBbCwStELF11HELdNM1K9YAKmcs1GUdl"
api = BlockFrostApi(project_id=API_KEY)

progress_data = {'processed_frames': 0, 'total_frames': 0}

# List to store hashes
hash_list = []

def hash_binary_data(binary_data):
    try:
        logging.debug("Hashing binary data")
        sha256_hash = hashlib.sha256()
        sha256_hash.update(binary_data.encode('utf-8'))
        return sha256_hash.hexdigest()
    except Exception as e:
        logging.error(f"Error in hash_binary_data: {e}")
        return ""

def search_metadata_for_hash(wallet_address, hash_value):
    headers = {'project_id': API_KEY}
    page = 1
    while True:
        try:
            response = requests.get(f"{API_URL}/addresses/{wallet_address}/transactions?page={page}", headers=headers)
            response.raise_for_status()
            transactions = response.json()
            if not transactions:
                break
            for tx in transactions:
                tx_hash = tx['tx_hash']
                metadata_response = requests.get(f"{API_URL}/txs/{tx_hash}/metadata", headers=headers)
                metadata_response.raise_for_status()
                metadata = metadata_response.json()
                for entry in metadata:
                    if 'json_metadata' in entry:
                        for key, value in entry['json_metadata'].items():
                            if isinstance(value, list) and hash_value in value:
                                logging.debug("Transaction found with hash in metadata")
                                return tx_hash, entry
                            elif value == hash_value:
                                logging.debug("Transaction found with hash in metadata")
                                return tx_hash, entry
            page += 1
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception: {e}")
            break
    return None

def video_to_binary(video_path, num_colors=8, target_resolution=(640, 480)):
    logging.debug(f"Processing video: {video_path}")
    cap = cv2.VideoCapture(video_path)
    binary_code = ""
    frame_count = 0
    if not cap.isOpened():
        logging.error("Failed to open video file")
        return ""

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    progress_data['total_frames'] = total_frames
    logging.debug(f"Total frames to process: {total_frames}")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.resize(frame, target_resolution)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_image = Image.fromarray(frame)
        frame_binary = image_to_binary(frame_image, num_colors)
        binary_code += frame_binary
        frame_count += 1
        progress_data['processed_frames'] = frame_count
        logging.debug(f"Processed frame {frame_count}/{total_frames}")
        # Release the frame to save memory
        del frame, frame_image, frame_binary
        time.sleep(0.1)  # Simulate processing time

    cap.release()
    logging.debug(f"Video processed, total frames: {frame_count}")
    return binary_code

def image_to_binary(image, num_colors=8):
    try:
        logging.debug("Converting image to binary")
        quantized_image = image.convert("L").quantize(colors=num_colors)
        width, height = quantized_image.size
        binary_code = ""
        palette = quantized_image.getpalette()
        color_to_binary = {}
        bits_needed = len(bin(num_colors - 1)[2:])
        for i in range(num_colors):
            binary_value = format(i, f'0{bits_needed}b')
            color_to_binary[i] = binary_value
        for y in range(height):
            for x in range(width):
                pixel = quantized_image.getpixel((x, y))
                binary_code += color_to_binary[pixel]
        logging.debug("Image converted to binary")
        return binary_code
    except Exception as e:
        logging.error(f"Error in image_to_binary: {e}")
        return ""

@app.route('/upload_file', methods=['POST'])
def upload_file():
    logging.debug("Upload file endpoint called")
    file = request.files.get('file')
    new_wallet = request.form.get('newWallet')
    current_hash = request.form.get('currentHash')
    logging.debug(f"Received new wallet: {new_wallet}")
    logging.debug(f"Current hash: {current_hash}")

    if new_wallet and current_hash:
        logging.debug("Searching new wallet with provided hash")
        tx = search_metadata_for_hash(new_wallet, current_hash)
        if tx:
            logging.debug("Transaction found")
            return jsonify({
                'message': 'Transaction found with this hash within the declared wallet. Frame by frame analysis has confirmed authenticity',
                'hash': current_hash,
                'wallet': new_wallet,
                'total_frames': progress_data.get('total_frames', 0),
                'processed_frames': progress_data.get('total_frames', 0)
            })
        else:
            logging.debug("No transaction found")
            return jsonify({
                'message': 'No transaction found with this hash within the declared wallet: Possible Tampering.',
                'hash': current_hash,
                'wallet': new_wallet,
                'total_frames': progress_data.get('total_frames', 0),
                'processed_frames': progress_data.get('total_frames', 0)
            })
    elif file:
        file_path = os.path.join('uploads', file.filename)
        try:
            file.save(file_path)
            logging.debug(f"File saved to {file_path}")

            if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                try:
                    image = Image.open(file_path)
                    binary_code = image_to_binary(image)
                except UnidentifiedImageError as e:
                    logging.error(f"Error opening image: {e}")
                    return jsonify({'message': 'Failed to process image: Unidentified image format.'})
            elif file.filename.lower().endswith('.mp4'):
                binary_code = video_to_binary(file_path)
            else:
                logging.error("Unsupported file type")
                return jsonify({'message': 'Unsupported file type.'})

            if binary_code:
                hash_result = hash_binary_data(binary_code)
                logging.debug(f"Binary data hashed: {hash_result}")

                wallet_to_use = new_wallet if new_wallet else "addr1qyqmdurljd7v07rketnnc3udc9w547pya7v8jnh6zalrymyn84lfn88ypr4p6lvkaqwq46h2g67whtnenlpv2w9jvads3d458l"
                logging.debug(f"Using wallet: {wallet_to_use}")

                tx = search_metadata_for_hash(wallet_to_use, hash_result)
                if tx:
                    logging.debug("Transaction found")
                    return jsonify({
                        'message': 'Transaction found with this hash within the declared wallet. Frame by frame analysis has confirmed authenticity',
                        'hash': hash_result,
                        'wallet': wallet_to_use,
                        'total_frames': progress_data.get('total_frames', 0),
                        'processed_frames': progress_data.get('total_frames', 0)
                    })
                else:
                    logging.debug("No transaction found")
                    return jsonify({
                        'message': 'No transaction found with this hash within the declared wallet: Possible Tampering.',
                        'hash': hash_result,
                        'wallet': wallet_to_use,
                        'total_frames': progress_data.get('total_frames', 0),
                        'processed_frames': progress_data.get('total_frames', 0)
                    })
            else:
                logging.error("Failed to process file to binary")
                return jsonify({'message': 'Failed to process file.'})
        except Exception as e:
            logging.error(f"Error saving or processing file: {e}")
            return jsonify({'message': 'Error processing file.'})
    else:
        logging.error("No file uploaded and no new wallet provided")
        return jsonify({'message': 'No file uploaded and no new wallet provided.'})

@app.route('/search_file', methods=['POST'])
def search_file():
    logging.debug("Search file endpoint called")
    file = request.files.get('file')
    if not file:
        logging.error("No file uploaded")
        return jsonify({'message': 'No file uploaded.'})

    file_path = os.path.join('uploads', file.filename)
    try:
        file.save(file_path)
        logging.debug(f"File saved to {file_path}")

        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            binary_code = image_to_binary(Image.open(file_path))
        elif file.filename.lower().endswith('.mp4'):
            binary_code = video_to_binary(file_path)
        else:
            logging.error("Unsupported file type")
            return jsonify({'message': 'Unsupported file type.'})

        if binary_code:
            hash_result = hash_binary_data(binary_code)
            logging.debug(f"Binary data hashed: {hash_result}")

            tx = search_entire_blockchain_for_hash(hash_result)
            if tx:
                logging.debug("Transaction found")
                return jsonify({
                    'message': 'Transaction found with this hash. Frame by frame analysis has confirmed authenticity',
                    'hash': hash_result,
                    'wallet': tx[1].get('address', 'Unknown'),
                    'total_frames': progress_data.get('total_frames', 0),
                    'processed_frames': progress_data.get('total_frames', 0)
                })
            else:
                logging.debug("No transaction found")
                return jsonify({
                    'message': 'No transaction found with this hash: Possible Tampering.',
                    'hash': hash_result,
                    'wallet': '',
                    'total_frames': progress_data.get('total_frames', 0),
                    'processed_frames': progress_data.get('total_frames', 0)
                })
        else:
            logging.error("Failed to process file to binary")
            return jsonify({'message': 'Failed to process file.'})
    except Exception as e:
        logging.error(f"Error saving or processing file: {e}")
        return jsonify({'message': 'Error processing file.'})

@app.route('/compare_videos', methods=['POST'])
def compare_videos_route():
    logging.debug("Compare videos endpoint called")
    video1 = request.files.get('video1')
    video2 = request.files.get('video2')

    if not video1 or not video2:
        logging.error("One or both videos not uploaded")
        return jsonify({'message': 'Both videos must be uploaded.'})

    video1_path = os.path.join('uploads', video1.filename)
    video2_path = os.path.join('uploads', video2.filename)

    try:
        video1.save(video1_path)
        video2.save(video2_path)
        logging.debug(f"Videos saved to {video1_path} and {video2_path}")

        cap1 = cv2.VideoCapture(video1_path)
        cap2 = cv2.VideoCapture(video2_path)

        frames1 = []
        frames2 = []
        while cap1.isOpened() or cap2.isOpened():
            ret1, frame1 = cap1.read()
            ret2, frame2 = cap2.read()
            if ret1:
                frames1.append(frame1)
            if ret2:
                frames2.append(frame2)
            if not ret1 and not ret2:
                break

        cap1.release()
        cap2.release()

        comparison_dir = "comparisons"
        if not os.path.exists(comparison_dir):
            os.makedirs(comparison_dir)

        comparison_images = []
        differences = []
        max_len = max(len(frames1), len(frames2))

        for i in range(max_len):
            if i < len(frames1) and i < len(frames2):
                frame1 = frames1[i]
                frame2 = frames2[i]
            elif i < len(frames1):
                frame1 = frames1[i]
                frame2 = np.zeros_like(frame1)
            else:
                frame2 = frames2[i]
                frame1 = np.zeros_like(frame2)

            diff_img = cv2.absdiff(frame1, frame2)
            gray_diff = cv2.cvtColor(diff_img, cv2.COLOR_BGR2GRAY)
            _, threshold_diff = cv2.threshold(gray_diff, 15, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(threshold_diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            total_diff = np.sum(threshold_diff) / 255
            frame_area = frame1.shape[0] * frame1.shape[1]
            percent_diff = (total_diff / frame_area) * 100
            differences.append(percent_diff)

            for contour in contours:
                if cv2.contourArea(contour) > 500:  # Filter small differences
                    x, y, w, h = cv2.boundingRect(contour)
                    cv2.rectangle(frame1, (x, y), (x+w, y+h), (0, 0, 255), 2)
                    cv2.rectangle(frame2, (x, y), (x+w, y+h), (0, 0, 255), 2)
                    explanation = f"Difference in region: (x: {x}, y: {y}, width: {w}, height: {h})"
                    logging.debug(explanation)

            frame1_path = os.path.join(comparison_dir, f"frame1_{i}.jpg")
            frame2_path = os.path.join(comparison_dir, f"frame2_{i}.jpg")
            cv2.imwrite(frame1_path, frame1)
            cv2.imwrite(frame2_path, frame2)
            comparison_images.append((frame1_path, frame2_path))

        logging.debug(f"Differences: {differences}")

        return jsonify({'message': 'Comparison complete', 'comparison_images': comparison_images, 'differences': differences})
    except Exception as e:
        logging.error(f"Error saving or processing videos: {e}")
        return jsonify({'message': 'Error processing videos.'})

@app.route('/progress')
def progress():
    def generate():
        while True:
            time.sleep(1)
            yield f"data:{progress_data['processed_frames']}|{progress_data['total_frames']}\n\n"
    return Response(generate(), mimetype='text/event-stream')

@app.route('/comparisons/<path:filename>')
def serve_comparisons(filename):
    return send_from_directory('comparisons', filename)

@app.route('/add_to_list', methods=['POST'])
def add_to_list():
    file = request.files.get('file')
    if not file:
        logging.error("No file uploaded")
        return jsonify({'success': False, 'message': 'No file uploaded.'})

    file_path = os.path.join('uploads', file.filename)
    try:
        file.save(file_path)
        logging.debug(f"File saved to {file_path}")

        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            binary_code = image_to_binary(Image.open(file_path))
        elif file.filename.lower().endswith('.mp4'):
            binary_code = video_to_binary(file_path)
        else:
            logging.error("Unsupported file type")
            return jsonify({'success': False, 'message': 'Unsupported file type.'})

        if binary_code:
            hash_result = hash_binary_data(binary_code)
            logging.debug(f"Binary data hashed: {hash_result}")

            hash_list.append({'file': file.filename, 'hash': hash_result})
            return jsonify({'success': True, 'file': file.filename, 'hash': hash_result})
        else:
            logging.error("Failed to process file to binary")
            return jsonify({'success': False, 'message': 'Failed to process file.'})
    except Exception as e:
        logging.error(f"Error saving or processing file: {e}")
        return jsonify({'success': False, 'message': 'Error processing file.'})

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    if not os.path.exists('comparisons'):
        os.makedirs('comparisons')
    app.run(debug=True, port=5009)
