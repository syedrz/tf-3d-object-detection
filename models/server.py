import frustum_point_net, frustum_proposal, ssd_mobile_net
import numpy as np
from configs import configs
from utils import utils


class Server(object):

	frt_proposal_server = None
	detector_2d = None
	detector_3d = None
	in_progress = False
	CALIB_PARAM = configs.CALIB_PARAM
	NUM_POINT = configs.NUM_POINT
	FPNET_MODEL_PATH = configs.FPNET_MODEL_PATH
	NUM_HEADING_BIN = configs.NUM_HEADING_BIN
	SSD_MOBILE_NET_MODEL_PATH = configs.SSD_MOBILE_NET_MODEL_PATH
	input_tensor_names = configs.input_tensor_names
	output_tensor_names = configs.output_tensor_names
	device = configs.device

	def __init__(self):
		self._load_params()
		self._init_detector_2d()
		self._init_frt_proposal_server()
		self._init_detector_3d()

	def _load_params(self):
		self.calib_param = self.CALIB_PARAM

	def _init_frt_proposal_server(self):
		self.frt_proposal_server = frustum_proposal.FrustumProposal(self.calib_param)

	def _init_detector_2d(self):
		self.detector_2d = ssd_mobile_net.SSDMobileNet(
			model_fp=self.SSD_MOBILE_NET_MODEL_PATH,
			input_tensor_names=self.input_tensor_names,
			output_tensor_names=self.output_tensor_names,
			device=self.device)

	def _init_detector_3d(self):
		self.detector_3d = frustum_point_net.FPNetPredictor(model_fp=self.FPNET_MODEL_PATH)

	def predict(self, inputs):
		# Process one image and one frame of point cloud at once
		assert 'img' and 'pclds' in inputs
		self.in_progress = True

		# Step1: 2D Detector
		bboxes_2d, one_hot_vectors = self.detector_2d.inference_vebose(inputs['img'])

		# Step2: Get Frustum Proposals
		f_prop_cam_all, f_prop_velo_all = self.frt_proposal_server.get_frustum_proposal(inputs['img'].shape, bboxes_2d, inputs['pclds'])

		# Step3: Down sampling points in Frustum Proposals
		for idx, f_prop_cam in enumerate(f_prop_cam_all):
			choice = np.random.choice(f_prop_cam.shape[0], self.NUM_POINT, replace=True)
			f_prop_cam_all[idx] = f_prop_cam[choice, :]

		# Step4: Detect 3D Bounding Boxes from Frustum Proposals
		logits, centers, \
		heading_logits, heading_residuals, \
		size_scores, size_residuals = self.detector_3d.predict(pc=f_prop_cam_all, one_hot_vec=one_hot_vectors)

		# Step5: Post-process and Visualizations
		for idx in range(len(centers)):

			heading_class = np.argmax(heading_logits, 1)
			size_logits = size_scores
			size_class = np.argmax(size_logits, 1)
			size_residual = np.vstack([size_residuals[0, size_class[idx], :]])
			heading_residual = np.array([heading_residuals[idx, heading_class[idx]]])  # B,
			heading_angle = utils.class2angle(heading_class[idx], heading_residual[idx], self.NUM_HEADING_BIN)
			box_size = utils.class2size(size_class[idx], size_residual[idx])
			corners_3d = utils.get_3d_box(box_size, heading_angle, centers[idx])

			corners_3d_in_velo_frame = np.zeros_like(corners_3d)
			centers_in_velo_frame = np.zeros_like(centers)
			corners_3d_in_velo_frame[:, 0:3] = self.frt_proposal_server.project_rect_to_velo(corners_3d[:, 0:3])
			centers_in_velo_frame[:, 0:3] = self.frt_proposal_server.project_rect_to_velo(centers[:, 0:3])

			# Step4, Visualization
			utils.viz(inputs['pclds'], centers_in_velo_frame, corners_3d_in_velo_frame, f_prop_velo_all[idx])

		self.in_progress = False