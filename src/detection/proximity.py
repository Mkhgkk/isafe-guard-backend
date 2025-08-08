import cv2
import numpy as np
import time
from boxmot import BotSort
import miniball
from pathlib import Path
import torch
from typing import List, Tuple
from detection import draw_text_with_background
from ultralytics.engine.results import Results
from config import FRAME_HEIGHT, FRAME_WIDTH

# cls_names = ['Worker', 'Hard hat', 'Grab Crane', 'Forklift', 'Signaler', 'Grab Crane Arm']
cls_names = [
    "Backhoe loader",
    "Cement truck", 
    "Compactor",
    "Dozer",
    "Dump truck",
    "Excavator",
    "Grader",
    "Mobile crane",
    "Tower crane",
    "Wheel loader",
    "Worker",
    "Hard hat",
    "Red hardhat",
    "Scaffolds",
    "Lifted load",
    "Crane hook",
    "Hook"
]

WORKER_CLASSES = ['Worker']
# VEHICLE_CLASSES = ['Forklift', 'Grab Crane', 'Grab Crane Arm']

VEHICLE_CLASSES = [
    "Backhoe loader",
    "Cement truck",
    "Compactor",
    "Dozer",
    "Dump truck",
    "Excavator",
    "Grader",
    "Mobile crane",
    "Tower crane",
    "Wheel loader"
]

DANGER_DIST_METERS = 2  # in meters
VEHICLE_MOVING_THRESH = 10

device = torch.device("cuda")

# Initialize the tracker
tracker = BotSort(
    reid_weights=Path("osnet_x0_25_msmt17.pt"),  # Path to ReID model
    device=device,  # Use CPU for inference
    half=False,
    with_reid=False,
    track_buffer=150,
    cmc_method="sof",
    frame_rate=20,
    new_track_thresh=0.3,
)

clicked_pts = [(500, 300), (700, 300), (750, 500), (560, 600)]

image_coords = np.float32(clicked_pts)
real_world_coords = np.float32([[0, 0], [2, 0], [2, 4.5], [0, 4.5]])
homography_matrix = cv2.getPerspectiveTransform(image_coords, real_world_coords)

def get_bottom_center(box):
    x1, y1, x2, y2 = box
    return np.array([[[(x1 + x2) / 2, y2]]], dtype=np.float32)


def get_worker_center(box):
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2], dtype=np.float32)


def transform_to_world(pt):
    return cv2.perspectiveTransform(pt, homography_matrix)[0][0]



def get_vehicle_ground_edges(box):
    x1, y1, x2, y2 = box
    return [
        np.array([[[(x1 + x2) / 2, y2]]], dtype=np.float32),
        np.array([[[x1, y2]]], dtype=np.float32),
        np.array([[[x2, y2]]], dtype=np.float32),
    ]

font = cv2.FONT_HERSHEY_SIMPLEX
prev_time = time.time()

def detect_proximity(
    image: np.ndarray, results: List[Results]
) -> Tuple[str, List[str], List[Tuple[int, int, int, int]]]:
    results = results[0]  # Assuming results is a list of Results objects
    
    final_status = "Safe"

    worker_positions = []
    vehicle_positions = []
    Grab_crane_box, cran_arm_box, forklift_box = [], [], []
    worker_box, hat_box, signaler_box = [], [], []



    dets =  []

    for result in results.boxes.data: # type: ignore
        x1, y1, x2, y2, conf, cls = result.tolist()
        # cls_name = model.names[int(cls)]
        cls_name = cls_names[int(cls)]
        box = [int(x1), int(y1), int(x2), int(y2)]

        # Tracking
        dets.append([*box, conf, cls])

    # Convert detections to numpy array (N X (x, y, x, y, conf, cls))
    dets = np.array(dets)

    # Update the tracker
    trk_res = tracker.update(dets, image)  # --> M X (x, y, x, y, id, conf, cls, ind)




    for trk in tracker.active_tracks:
        if not trk.history_observations:
            continue
        if len(trk.history_observations) < 3:
            continue
        cls_name = cls_names[int(trk.cls)]
        box = [int(x) for x in trk.history_observations[-1]]
        if cls_name in VEHICLE_CLASSES:
            cv2.rectangle(image, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
            cv2.putText(
                image,
                f"{cls_name}_id:{int(trk.id)}",
                (box[0], box[1] - 5),
                font,
                0.6,
                (0, 255, 0),
                2,
            )
            bottom_center = get_bottom_center(box)
            world_center = transform_to_world(bottom_center)
            vehicle_positions.append((world_center, trk))
            if cls_name == "Grab Crane":
                Grab_crane_box.append(box)
            elif cls_name == "Grab Crane Arm":
                cran_arm_box.append(box)
            elif cls_name == "Forklift":
                forklift_box.append(box)

        elif cls_name == "Worker":
            # worker_box.append(box)
            worker_box.append(trk)
        elif cls_name == "Hard hat":
            hat_box.append(box)
            cv2.rectangle(image, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
        elif cls_name == "Red hardhat":
            signaler_box.append(box)
            cv2.rectangle(image, (box[0], box[1]), (box[2], box[3]), (255, 255, 0), 2)

    
    for w_box in worker_box:
        # center = get_worker_center(w_box[:4])
        box = [int(x) for x in w_box.history_observations[-1]]
        center = get_worker_center(box)

        label = None
        color = (0, 255, 0)

        is_signaler = any(
            box[0] <= (sBox[0] + sBox[2]) / 2 < box[2] and sBox[1] >= box[1] - 20
            for sBox in signaler_box
        )

        is_driver = any(
            ca_box[1] - 50 < center[1] < ca_box[3] + 50 for ca_box in cran_arm_box
        ) or any(
            (center[1] < (g_box[1] + g_box[3]) / 2) or (g_box[3] > box[1])
            for g_box in Grab_crane_box
        )

        has_helmet = any(
            box[0] <= (hatBox[0] + hatBox[2]) / 2 < box[2] and hatBox[1] >= box[1] - 20
            for hatBox in hat_box
        )

        add_id = f"_id:{w_box.id}"
        if is_signaler:
            label = "Signaler" + add_id
            color = (255, 255, 0)
        elif is_driver:
            if has_helmet:
                label = "Driver with helmet" + add_id
                color = (0, 180, 255)
            else:
                label = "Driver without helmet" + add_id
                color = (0, 0, 255)
        else:
            if has_helmet:
                label = "Worker with helmet" + add_id
                color = (0, 180, 0)
            else:
                label = "Worker without helmet" + add_id
                color = (0, 0, 255)

        # -------- BLUR FACE (TOP 40%) --------
        if any(label.startswith(role) for role in ["Worker", "Driver", "Signaler"]):
            # x1, y1, x2, y2 = w_box
            x1, y1, x2, y2 = box
            blur_height = int(0.4 * (y2 - y1))
            y1_blur = y1
            y2_blur = y1 + blur_height

            if y2_blur > y1_blur and x2 > x1:
                face_region = image[y1_blur:y2_blur, x1:x2]
                if face_region.size > 0:
                    # blurred = cv2.GaussianBlur(face_region, (15, 15), 0)
                    blurred = cv2.blur(face_region, (7, 7))
                    # h, w = face_region.shape[:2]
                    # temp = cv2.resize(face_region, (w//10, h//10), interpolation=cv2.INTER_LINEAR)
                    # blurred = cv2.resize(temp, (w, h), interpolation=cv2.INTER_NEAREST)
                    image[y1_blur:y2_blur, x1:x2] = blurred

        # -------- DRAW LABEL AND BOX --------
        cv2.rectangle(
            image, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), color, 2
        )
        cv2.putText(image, label, (int(box[0]), int(box[1]) - 10), font, 0.6, color, 2)

        # if label in ['Worker with helmet', 'Worker without helmet']:
        if "Worker with helmet" in label or "Worker without helmet" in label:
            bottom_center = get_bottom_center(box)

            world_center = transform_to_world(bottom_center)
            worker_positions.append((world_center, box))

        
    # ---------------- PROXIMITY CHECK ----------------
    for w_pt, w_box in worker_positions:
        for v_world_pt, v_box in vehicle_positions:
            # check history:
            if len(v_box.history_observations) < 10:
                continue

            centroids = np.array(
                [
                    [int((x1 + x2) / 2), int((y1 + y2) / 2)]
                    for (x1, y1, x2, y2) in v_box.history_observations
                ]
            )
            # Step 2: Remove duplicates (recommended)
            centroids = np.unique(centroids, axis=0)
            # Step 3: Compute the minimum enclosing ball
            center, radius_squared = miniball.get_bounding_ball(centroids)
            radius = radius_squared**0.5

            if radius < VEHICLE_MOVING_THRESH:
                continue
            v_box1 = [int(x) for x in v_box.history_observations[-1]]
            vehicle_candidates = get_vehicle_ground_edges(v_box1)
            vehicle_world_pts = [transform_to_world(p) for p in vehicle_candidates]
            closest_v_pt = min(
                vehicle_world_pts, key=lambda p: np.linalg.norm(p - w_pt)
            )

            dist = np.linalg.norm(w_pt - closest_v_pt)
            color = (0, 0, 255) if dist < DANGER_DIST_METERS else (0, 255, 0)

            if dist < DANGER_DIST_METERS:
                cv2.putText(
                    image,
                    f"ALERT: {dist:.2f}m",
                    (int(w_box[0]), int(w_box[1]) - 10),
                    font,
                    0.6,
                    color,
                    2,
                )

            pt1 = (int((w_box[0] + w_box[2]) // 2), int(w_box[3]))
            pt2 = (int((v_box1[0] + v_box1[2]) // 2), int(v_box1[3]))
            cv2.line(image, pt1, pt2, color, 2)
            cv2.putText(
                image,
                f"{dist:.2f}m",
                ((int(pt1[0]) + pt2[0]) // 2, (pt1[1] + pt2[1]) // 2),
                font,
                0.6,
                color,
                2,
            )















    return "unsafe", [], []