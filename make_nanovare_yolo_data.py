import json
import os
from pathlib import Path
import shutil
import cv2
from tqdm import tqdm
from sklearn import model_selection

from nanovare_casa_core.utils import supervisely as sly
from nanovare_casa_core.utils import constants

# annotation classes
ANNOTATION_CLASSES_TO_ID = {"sperm": 0}


def init_supervisely_dataset(dir_name, root_dir, dataset_filter_id=None):
    api = sly.Api(
        token=os.getenv("SUPERVISELY_API_KEY"),
        root_dir=root_dir
    )
    api.download_project(
        constants.SUPERVISELY_LOCALISATION_PROJECT_ID,
        dataset_filter_id=dataset_filter_id,
        update=False,
        check=True
    )
    supervisely_image_dir = api.merge_project(
        constants.SUPERVISELY_LOCALISATION_PROJECT_ID,
        dataset_filter_id=dataset_filter_id,
        update=True,
        dir_name=dir_name
    )
    return supervisely_image_dir


def get_supervisely_data_dir(dir_name, root_dir):
    api = sly.Api(
        token=os.getenv("SUPERVISELY_API_KEY"),
        root_dir=root_dir
    )
    return api.get_project_dir(project_id=constants.SUPERVISELY_LOCALISATION_PROJECT_ID, dir_name=dir_name)


def filter_image_path_list(image_path_list):
    discard_path_list = []

    for frame_path in image_path_list:
        annotation_path = frame_path.parents[1] / "ann" / (frame_path.name + ".json")
        if not annotation_path.is_file():
            annotation_data = {
                    "description": "",
                    "tags": [],
                    "size": {
                        "height": 1200,
                        "width": 1920
                    },
                    "objects": []
                }
            json.dump(annotation_data, open(annotation_path, 'w'))
        with annotation_path.open() as annotation_file:
            annotation_data = json.load(annotation_file)

        discard = False
        # Remove images with "To ignore" tag
        for tag in annotation_data["tags"]:
            if tag["name"] == "To ignore":
                discard = True
                break
        # Remove images with no objects (to remove images not tagged yet)
        if len(annotation_data["objects"]) == 0:
            discard = True

        if discard:
            discard_path_list.append(frame_path)
    return list(set(image_path_list) - set(discard_path_list))


def convert_supervisely_to_yolo(supervisely_data_dir, yolo_data_dir, color, copy_dir=None):
    image_path_list = list(supervisely_data_dir.glob("**/*.png"))
    dataset_length_supervisely = len(image_path_list)
    image_path_list = filter_image_path_list(image_path_list)
    print(f"Keep {len(image_path_list)} images out of {dataset_length_supervisely} supervisely images")
    image_stem_list = list(map(lambda x: x.stem, image_path_list))

    if yolo_data_dir.exists():
        shutil.rmtree(yolo_data_dir)

    if copy_dir is not None:
        train_stem = list(map(lambda x: x.stem, list((Path(copy_dir) / "images" / "train").glob("*.jpg"))))
        valid_stem = list(map(lambda x: x.stem, list((Path(copy_dir) / "images" / "val").glob("*.jpg"))))
    else:
        train_stem, valid_stem = model_selection.train_test_split(image_stem_list,
                                                                  test_size=0.25,
                                                                  shuffle=True,
                                                                  random_state=42)

    assert set(valid_stem + train_stem).issubset(image_stem_list)
    yolo_data_dir = Path(yolo_data_dir).resolve()
    if yolo_data_dir.exists():
        shutil.rmtree(yolo_data_dir)

    for frame_path in tqdm(image_path_list, "Converting to YOLO format"):

        if color == "bgr":
            image = cv2.imread(str(frame_path), 1)
        elif color == "green":
            image = cv2.imread(str(frame_path), 1)[:, :, 1]
        elif color == "gray":
            image = cv2.imread(str(frame_path), 0)
        else:
            raise ValueError("Wrong color")
        if frame_path.stem in train_stem:
            folder = "train"
        elif frame_path.stem in valid_stem:
            folder = "val"
        yolo_image_path = yolo_data_dir / "images" / folder / f"{frame_path.stem}.jpg"
        yolo_annotation_path = yolo_data_dir / "labels" / folder / f"{frame_path.stem}.txt"
        yolo_image_path.parent.mkdir(parents=True, exist_ok=True)
        yolo_annotation_path.parent.mkdir(parents=True, exist_ok=True)

        annotation_path = frame_path.parents[1] / "ann" / (frame_path.name + ".json")

        with annotation_path.open() as annotation_file:
            annotation_data = json.load(annotation_file)

        convert_supervisely_to_yolo_image(image, yolo_image_path, annotation_data, yolo_annotation_path)

    return yolo_data_dir / "images" / "train", yolo_data_dir / "images" / "val"


def convert_supervisely_to_yolo_image(image, yolo_image_path, annotation_data, yolo_annotation_path, w=80):
    cv2.imwrite(yolo_image_path.as_posix(), image)
    im_height, im_width = image.shape[:2]
    with yolo_annotation_path.open("w") as f:
        for obj in annotation_data["objects"]:
            if obj["classTitle"] not in ANNOTATION_CLASSES_TO_ID:
                continue
            class_id = ANNOTATION_CLASSES_TO_ID[obj["classTitle"]]
            x = obj["points"]["exterior"][0][0]
            y = obj["points"]["exterior"][0][1]
            bbox = [x, y, w, w]

            # Only keep sperm for now
            if class_id == 0:
                f.write(f"{class_id} {bbox[0]/im_width:.6f} {bbox[1]/im_height:.6f} {bbox[2]/im_width:.6f} {bbox[3]/im_height:.6f}\n")