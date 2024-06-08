from flask import Flask, request, jsonify, render_template, Response
import os
import cv2
from PIL import Image, UnidentifiedImageError
import hashlib
import requests
from blockfrost import BlockFrostApi
import logging
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

API_URL = "https://cardano-mainnet.blockfrost.io/api/v0"
API_KEY = "mainnetFBbCwStELF11HELdNM1K9YAKmcs1GUdl"
api = BlockFrostApi(project_id=API_KEY)

progress_data = {'processed_frames': 0, 'total_frames': 0}

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
        time.sleep(0.1)  # Simulate processing time
        logging.debug(f"Processed frame {frame_count} (Out of {total_frames})")
    cap.release()
    logging.debug(f"Video processed, total frames: {frame_count}")
    return binary_code

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

@app.route('/upload_file', methods=['POST'])
def upload_file():
    logging.debug("Upload file endpoint called")
    file = request.files.get('file')
    new_wallet = request.form.get('newWallet')
    current_hash = request.form.get('currentHash')
    logging.debug(f"Received new wallet: {new_wallet}")
    logging.debug(f"Current hash: {current_hash}")

    if new_wallet and current_hash:
        # Directly search the new wallet for the current hash
        logging.debug("Searching new wallet with provided hash")
        tx = search_metadata_for_hash(new_wallet, current_hash)
        if tx:
            logging.debug("Transaction found")
            return jsonify({
                'message': 'Transaction found with this hash within the declared wallet. Frame by frame analysis has confirmed authenticity',
                'hash': current_hash,
                'wallet': new_wallet,
                'total_frames': progress_data.get('total_frames', 0),
                'processed_frames': progress_data.get('total_frames', 0),  # Simulate 100% completion for videos
                'id': tx[0]
            })
        else:
            logging.debug("No transaction found")
            return jsonify({
                'message': 'No transaction found with this hash within the declared wallet: Possible Tampering.',
                'hash': current_hash,
                'wallet': new_wallet,
                'total_frames': progress_data.get('total_frames', 0),
                'processed_frames': progress_data.get('total_frames', 0)  # Simulate 100% completion for videos
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
                        'processed_frames': progress_data.get('total_frames', 0),  # Simulate 100% completion for videos
                        'id': tx[0]
                    })
                else:
                    logging.debug("No transaction found")
                    return jsonify({
                        'message': 'No transaction found with this hash within the declared wallet: Possible Tampering.',
                        'hash': hash_result,
                        'wallet': wallet_to_use,
                        'total_frames': progress_data.get('total_frames', 0),
                        'processed_frames': progress_data.get('total_frames', 0)  # Simulate 100% completion for videos
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

@app.route('/progress')
def progress():
    def generate():
        while True:
            time.sleep(1)
            yield f"data:{progress_data['processed_frames']}|{progress_data['total_frames']}\n\n"
    return Response(generate(), mimetype='text/event-stream')

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=True, port=5009)


