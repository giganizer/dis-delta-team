import rclpy
from rclpy.node import Node

from delta_interfaces.msg import GreeterJob
from delta_interfaces.msg import JobStatus
from threading import Thread

import time
import os

# speech work imports
import pyttsx3
# import librosa # no longer used
import speech_recognition as sr

# robot controller imports
from geometry_msgs.msg import Quaternion, PoseStamped
from nav2_msgs.action import Spin, NavigateToPose
from turtle_tf2_py.turtle_tf2_broadcaster import quaternion_from_euler
from rclpy.action import ActionClient

# publishing markers
from visualization_msgs.msg import Marker
from geometry_msgs.msg import PointStamped
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from builtin_interfaces.msg import Duration
from irobot_create_msgs.msg import AudioNoteVector, AudioNote

class RobotController:

    def __init__(self, node):
    
        self._arrived = False
        self._rotation_complete = False
        self._node = node
        
        # ROS2 Action clients
        self._nav_to_pose_client = ActionClient(self._node, NavigateToPose, 'navigate_to_pose')
        self._spin_client = ActionClient(self._node, Spin, 'spin')
        
        self._move_x = None
        self._move_y = None
        self._move_rot = None
        self._rotate_rot = None
        
        
    def YawToQuaternion(self, angle_z = 0.):
        quat_tf = quaternion_from_euler(0, 0, angle_z)

        # Convert a list to geometry_msgs.msg.Quaternion
        quat_msg = Quaternion(x=quat_tf[0], y=quat_tf[1], z=quat_tf[2], w=quat_tf[3])
        return quat_msg


    def move_to_position(self, x, y, rot):
        self._move_x = x
        self._move_y = y
        self._move_rot = rot
        
        self._arrived = False
          
        # building the message
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = 'map'
        goal_pose.header.stamp = self._node.get_clock().now().to_msg()
        goal_pose.pose.position.x = x
        goal_pose.pose.position.y = y
        goal_pose.pose.orientation = self.YawToQuaternion(rot)
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = goal_pose
        goal_msg.behavior_tree = ''
        
        while not self._nav_to_pose_client.wait_for_server(timeout_sec=1.0):
            self._node.get_logger().info("'NavigateToPose' action server not available, waiting...")
        
        self._node.get_logger().info('Navigating to goal (x,y,rot): ' + str(goal_pose.pose.position.x) + ' ' +
                  str(goal_pose.pose.position.y) + ' ' + str(rot))
                  
        self._send_move_goal_future = self._nav_to_pose_client.send_goal_async(goal_msg, feedback_callback=self.feedback_callback)
        
        self._send_move_goal_future.add_done_callback(self.move_goal_response_callback)
        
    def rotate(self, spin_dist_in_degree):
        self._rotate_rot = spin_dist_in_degree
    
        self._rotation_complete = False
    
        goal_msg = Spin.Goal()
        goal_msg.target_yaw = spin_dist_in_degree
        
        while not self._spin_client.wait_for_server(timeout_sec=1.0):
            self._node.get_logger().info("'Spin' action server not available, waiting...")
        self._node.get_logger().info(f'Spinning to angle {goal_msg.target_yaw}....')
        
        self._send_rotate_goal_future = self._spin_client.send_goal_async(goal_msg, feedback_callback=self.feedback_callback)
        
        self._send_rotate_goal_future.add_done_callback(self.rotate_goal_response_callback)
        

    def move_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._node.get_logger().info('Goal rejected :(')
            self.move_to_position(self._move_x, self._move_y, self._move_rot)
            return

        self._node.get_logger().info('Goal accepted :)')

        self._get_move_result_future = goal_handle.get_result_async()
        self._get_move_result_future.add_done_callback(self.get_move_result_callback)
        
    def rotate_goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._node.get_logger().info('Goal rejected :(')
            self.rotate(self._rotate_rot)
            return

        self._node.get_logger().info('Goal accepted :)')

        self._get_rotate_result_future = goal_handle.get_result_async()
        self._get_rotate_result_future.add_done_callback(self.get_rotate_result_callback)


    def get_move_result_callback(self, future):
        result = future.result()
        self._arrived = True
        
    def get_rotate_result_callback(self, future):
        result = future.result()
        self._rotation_complete = True
        

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback


class Greeter(Node):

    def __init__(self):
        super().__init__('greeter')
        
        # information about the currently executed job
        self.currently_executing_job = False # is the job still beeing processed
        self.id_of_current_job = ""
        
        self.color1 = "nothing"
        self.color2 = "nothing"
        # the colors we are interested in
        self.colors_interest = ["red", "green", "blue", "yellow", "purple", "orange", "black", "white", ] 
        
        # publishing the jobs status
        self.publisher_ = self.create_publisher(JobStatus, 'job_status', 1)
        timer_period = 1.0  # seconds
        self.publish_status_timer = self.create_timer(timer_period, self.publish_status)
        
        # listen to incoming jobs
        self.subscription = self.create_subscription(GreeterJob, 'greeter_job', self.process_incoming_job, 1)
        self.subscription  # prevent unused variable warning
        
        # robot controller
        self.rc = RobotController(self)
        
        # For publishing the markers
        self.marker_pub = self.create_publisher(Marker, "/delta_nav_marker", QoSReliabilityPolicy.BEST_EFFORT)
        
        # speech work
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty("rate", 160) # default rate is 200; subtracting 40 seems to sound better
        self.recognizer = sr.Recognizer()

        self.cmd_audio_publisher = self.create_publisher(AudioNoteVector, "/cmd_audio", 1)
        

    def publish_status(self):
        msg = JobStatus()
        msg.acting = self.currently_executing_job
        msg.job_id = self.id_of_current_job
        msg.result_string1 = self.color1
        msg.result_string2 = self.color2
        self.publisher_.publish(msg)
        
        
    def process_incoming_job(self, msg):
        if self.id_of_current_job == msg.job_id or self.currently_executing_job == True:
            return
        else:
            self.id_of_current_job = msg.job_id
            self.currently_executing_job = True
            self.publish_status()

        thread = Thread(target=self.greet_a_person, args=(msg.position_x, msg.position_y, msg.position_z, msg.rotation, msg.person_id, msg.talk_to_person))
        thread.start()
        
    
    def greet_a_person(self, position_x, position_y, position_z, rotation, person_id, talk_to_person):
            
        person_id = int(person_id.split("_")[-1])

        # moving to person
        self.get_logger().info('moving to greet person at (x: %f  y: %f  rot: %f)' % (position_x, position_y, rotation))
        self.rc.move_to_position(position_x, position_y, rotation)
        while not self.rc._arrived:
                time.sleep(1)
                self.get_logger().info('waiting until robot arrives at person')
                # Publish a marker
                self.send_marker(position_x, position_y)
                self.send_marker(position_x - 0.1, position_y, 1, 0.15, "greet_person_nav_goal")
                
                
        if not talk_to_person:
            self.currently_executing_job = False
            self.publish_status()
            return
        
        
        self.send_marker(position_x - 0.3, position_y, 2, 0.25, "talking_to_person")
        
        self.sayText("Hello human. Can you tell me the color of the ring where I have to park?")
        
        # speech recognition

        text = None # init text to none

        # use microphone as source and listen
        with sr.Microphone() as source:
            print("I'm listening...\n")
            audio = self.recognizer.listen(source)

            # try to recognize using google api
            try:
                # recognize speech using Google Web Speech API - required an internet connection
                print("Recognizing with Google Web Speech API...")
                text = self.recognizer.recognize_google(audio)
                print("Successful.")
            except sr.UnknownValueError:
                # Google API didn't understand
                print("Google Web Speech API could not understand the audio.")
            except sr.RequestError as e:
                # problem with the API
                print(f"Could not request results from Google Web Speech API; {e}")
                print("Trying Sphinx instead...")
                try:
                    # recognize using Sphinx - alternative option and should also work offline
                    print("Recognizing with Sphinx...")
                    text = self.recognizer.recognize_sphinx(audio)
                    print("Successful.")
                except sr.UnknownValueError:
                    # Sphinx didnt understand
                    print("Sphinx could not understand audio")
                except sr.RequestError as e:
                    # error in Sphinx
                    print("Sphinx error; {0}".format(e))


        found_colors = [] # init to empty, will hold the colors picked up from listening

        # if entirely unsuccessful
        if text is None:
            # raise Exception("Speech recognition failed.")
            print("Speech recognition has failed. :(")
            self.sayText("Speech recognition has failed. :(")
        # otherwise pickup the colors
        else:
            text = text.lower()
            print(f"You said: {text}")
            self.sayText(f"You said: {text}")

            # lets check for colors...
            for word in text.split():
                # if word is a new color
                if word in self.colors_interest and  word not in found_colors:
                    found_colors.append(word)
        
        self.color1 = "nothing"
        self.color2 = "nothing"
        # response depending on the number of colors picked up
        if len(found_colors) == 0:
            print("No colors received (or something went wrong).")
            self.sayText("No colors received (or something went wrong).")
        elif len(found_colors) == 1:
            print("You only gave me one color: '{}'".format(found_colors[0]))
            self.sayText("You only gave me one color: '{}'".format(found_colors[0]))
            self.color1 = found_colors[0]
        elif len(found_colors) == 2:
            print("I received colors '{}' and '{}'".format(found_colors[0], found_colors[1]))
            self.sayText("I received colors '{}' and '{}'".format(found_colors[0], found_colors[1]))
            self.color1 = found_colors[0]
            self.color2 = found_colors[1]
        elif len(found_colors) >= 3:
            print(f"You gave me more than two colors: {found_colors}. I'm continuing with the first two.")
            self.sayText(f"You gave me more than two colors: {found_colors}. I'm continuing with the first two.")
            self.color1 = found_colors[0]
            self.color2 = found_colors[1]

        # # write answer into self.color1 and self.color2:
        # self.color1 = "nothing"
        # self.color2 = "nothing"
        # # or 
        # self.color1 = "green"
        # self.color2 = "red"
        
        # TODO:
        # We are supposed to approach multiple people and received colors from
        # them, so I'm not sure how these 2 colors in self are supposed to work. 
        # Probably needs some adjustment in terms of writing the answers into 
        # them, but I'm not sure how they are used elsewhere/later, so I'll hold
        # off for now. Should be very simple though...
        
        # IMPORTANT: after greeting has finished, set currently_executing_job to False
        self.currently_executing_job = False
        self.publish_status()
        
    def sayText(self, text):
        self.tts_engine.say(text)
        self.tts_engine.runAndWait()
    
    # this function is deprecated
    # def makeNoteArrayFromAudioFile(self, audiofilename):
    #     y, sr = librosa.load(audiofilename)

    #     # Calculate onset envelopes
    #     onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    #     # Detect onsets
    #     onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    #     # Extract pitches
    #     pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
    #     # Calculate time intervals
    #     hop_length = 512  # Adjust as needed
    #     frame_duration = hop_length / sr
    #     times = librosa.times_like(pitches, sr=sr, hop_length=hop_length)
    #     # Create list of (frequency, time_interval) pairs
    #     frequency_time_pairs = list(zip(pitches.max(axis=0), times))
    #     return frequency_time_pairs

    # this function is deprecated
    # def constructNoteVector(self, note_array):
    #     # from given note array, construct a irobot_create_msgs/msg/AudioNoteVector.notes
    #     output_notes = []
    #     for pair in note_array:
    #         # ew_note = {"frequency": pair[0], "max_runtime": Duration(sec=0, nanosec=int(round(pair[1]*1e9)))}
    #         new_note = AudioNote()
    #         new_note.frequency = int(round(pair[0]))
    #         new_note.max_runtime = Duration(sec=0, nanosec=int(round(pair[1]*1e9)))
    #         output_notes.append(new_note)

        # return output_notes

    def destroyNode(self):
        self.rc._nav_to_pose_client.destroy()
        super().destroy_node()
        
    def send_marker(self, x, y, marker_id = 0, scale = 0.1, text = ""):
        point_in_map_frame = PointStamped()
        point_in_map_frame.header.frame_id = "/map"
        point_in_map_frame.header.stamp = self.get_clock().now().to_msg()

        point_in_map_frame.point.x = x
        point_in_map_frame.point.y = y
        point_in_map_frame.point.z = 1.0
        
        marker = self.create_marker(point_in_map_frame, marker_id, scale, text)
        self.marker_pub.publish(marker)
            
            
    def create_marker(self, point_stamped, marker_id, scale, text):
        marker = Marker()

        marker.header = point_stamped.header
        
        if text == "":
            marker.type = marker.SPHERE
        else:
            marker.type = marker.TEXT_VIEW_FACING
            
        marker.action = marker.ADD
        marker.id = marker_id
        marker.lifetime = Duration(sec=2)
        marker.text = text

        # Set the scale of the marker
        scale = scale
        marker.scale.x = scale
        marker.scale.y = scale
        marker.scale.z = scale

        # Set the color
        marker.color.r = 0.0
        marker.color.g = 0.5
        marker.color.b = 0.1
        marker.color.a = 1.0

        # Set the pose of the marker
        marker.pose.position.x = point_stamped.point.x
        marker.pose.position.y = point_stamped.point.y
        marker.pose.position.z = point_stamped.point.z

        return marker



def main(args=None):
    rclpy.init(args=args)
    greeter = Greeter()
    rclpy.spin(greeter)
    
    greeter.destroyNode()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
