import rospy

from lowpass import LowPassFilter
from pid import PID
from yaw_controller import YawController
import csv

GAS_DENSITY = 2.858
ONE_MPH = 0.44704
brake_torque_to_keep_zero_speed = 450
speed_limit = 40*ONE_MPH # mph converted to m/s


class Controller(object):
    def __init__(self, vehicle_mass, fuel_capacity, brake_deadband,
                 decel_limit, accel_limit, wheel_radius, wheel_base, 
                 steer_ratio, max_lat_accel, max_steer_angle):
        # TODO: Implement
        
        rospy.loginfo("Controller init started")
        # Assign Inputs to class attributes
        self.vehicle_mass = vehicle_mass
        self.fuel_capacity = fuel_capacity
        self.brake_deadband = brake_deadband
        self.decel_limt = decel_limit
        self.accel_limit = accel_limit
        self.wheel_radius = wheel_radius
        
        # Create Lowpass filter attribute for linear speed values
        ts_lin = 0.02 # 50 Hz sample time
        tau_lin = 0.5 # cut-off frequency

        # Create Lowpass filter attribute for angular speed values
        ts_ang = 0.02 # 50 Hz sample time
        tau_ang = 5.0 # cut-off frequency
        
        self.lin_v_lowpassfilter = LowPassFilter(tau_lin, ts_lin)
        self.ang_v_lowpassfilter = LowPassFilter(tau_ang, ts_ang)
        
        # Throttle Controller Initialization:
        throttle_kp = 0.3
        throttle_ki = 0.2
        throttle_kd = 0.
        throttle_min = 0.0
        throttle_max = 0.4
        
        # Throttle Controller
        self.throttle_controller = PID(throttle_kp, throttle_ki, throttle_kd, throttle_min, throttle_max)
        
        # Steering Angle Controller
        steering_kp = 0.100
        steering_ki = 0.002
        steering_kd = 0.0632
        steering_max = 0.5*max_steer_angle
        steering_min = -0.5*max_steer_angle
        
        
        self.last_steering = 0.0
        self.last_target_vel_ang_z = 0.0
        self.last_brake_torque = 0.0

        self.steering_controller = PID(steering_kp, steering_ki, steering_kd, steering_min, steering_max)
        
        # Yaw Controller:
        self.yaw_controller = YawController(wheel_base, steer_ratio, 0.1, max_lat_accel, max_steer_angle)
        
        self.max_total_steering = max_steer_angle
        
        # Brake Controller Initialization:
        brake_kp = 600
        brake_ki = 100
        brake_kd = 250
        brake_min = 0.0
        brake_max = 1500
        
        # Brake Controller
        self.brake_controller = PID(brake_kp, brake_ki, brake_kd, brake_min, brake_max)

        # rospy.loginfo("Controller init finished")
        pass

    def control(self, current_vel_lin_x, current_vel_ang_z, target_vel_lin_x, target_vel_ang_z, dbw_enabled, delta_t):
        
        # TODO: Change the arg, kwarg list to suit your needs
        # Return throttle, brake_torque, steering
        # rospy.loginfo("Control function started")
        
        # Initialize throttle, brake & steering output
        throttle = brake_torque = steering = 0
        
        # If DBW is disabled reset PID and output control values = 0
        if dbw_enabled == 0:
            self.throttle_controller.reset()
            self.steering_controller.reset()
            self.brake_controller.reset()
            return throttle, brake_torque, steering # initial values, all 0
        
        # LowPassFilter current linear velocity
        current_vel_lin_x = self.lin_v_lowpassfilter.filt(current_vel_lin_x)

        # LowPassFilter current angular velocity
        current_vel_ang_z = self.ang_v_lowpassfilter.filt(current_vel_ang_z)

        #if target_vel_lin_x is None:
            #rospy.logerr("Error: target_vel_lin_x is None")
            
        #if current_vel_lin_x is None:
            #rospy.logerr("Error: current_vel_lin_x is None")

        target_vel_lin_x = min(speed_limit-0.5, target_vel_lin_x)    
        lin_x_vel_error = target_vel_lin_x - current_vel_lin_x        
        # rospy.loginfo("Linear speed error: %.2f, Linear speed target: %.2f, Linear speed current: %.2f", lin_x_vel_error, target_vel_lin_x, current_vel_lin_x)
        
        if lin_x_vel_error >= 1:
            self.last_brake_torque = 0 
            self.brake_controller.reset()
            
        # Calculate Throttle Control Value
        throttle = self.throttle_controller.step(lin_x_vel_error, delta_t)
        self.last_vel = current_vel_lin_x
        
        # Calculate Brake Control Value
        if lin_x_vel_error > 0:
            brake_lin_x_vel_error = 0;
        else:
            brake_lin_x_vel_error = lin_x_vel_error*-1
            
        brake_torque = self.brake_controller.step(brake_lin_x_vel_error, delta_t)
        brake_torque = min(brake_torque, self.last_brake_torque+25)
        rospy.loginfo("lin_x_vel_error: %.2f, brake_lin_x_vel_error: %.2f, brake_torque: %.2f, self.last_brake_torque: %.2f", lin_x_vel_error, brake_lin_x_vel_error, brake_torque, self.last_brake_torque)
        if brake_torque > 100:
            self.throttle_controller.reset()
        #self.last_brake_torque = brake_torque 
        
        # If car becomes to fast (tolerance 0.2 m/s) or car is really slow
        # then throttle has to be set to 0
        if current_vel_lin_x > (target_vel_lin_x+0.2) or target_vel_lin_x < 0.1:
            throttle = 0.0
        
        # Calculate Brake Value and potentially overwrite tharottle value to 0
        if current_vel_lin_x < 0.1 and target_vel_lin_x == 0.0:
            # rospy.loginfo("Vehicle in standstill and target velocity = 0 --> Brake against Creep needed")
            # Vehicle is in standstill (<0.1 m/s) and shall reside there, apply brake and release throttle
            throttle = 0.0
            brake_torque = brake_torque_to_keep_zero_speed # this torque is needed to brake against the creep and potential slopes due to automatic transmission
        elif lin_x_vel_error < 0 and throttle < 0.2:
            # Set speed is smaller than current speed and throttle is just a little bit engaged
            # rospy.loginfo("Braking needed!")
            #brake_torque = self.brake_controller.step(lin_x_vel_error, delta_t)
            #rospy.loginfo("lin_x_vel_error: %.2f, brake_torque: %.2f, self.last_brake_torque: %.2f", lin_x_vel_error, brake_torque, self.last_brake_torque)
            #brake_torque = min(brake_torque, self.last_brake_torque+25)
            self.last_brake_torque = brake_torque 
            
            """
            throttle = 0.0
            decel_req = min(abs(lin_x_vel_error) / (1.3 / current_vel_lin_x), abs(self.decel_limt))
            rospy.loginfo("decel_req: %.2f, self.decel_limt: %.2f", decel_req, abs(self.decel_limt))
            brake_torque = abs(decel_req) * self.vehicle_mass * self.wheel_radius
            
            brake_torque = min(brake_torque, self.last_brake_torque+25)
            rospy.loginfo("self.last_brake_torque: %.2f, brake_torque: %.2f", self.last_brake_torque, brake_torque)
            self.last_brake_torque = brake_torque
            """
            
        
        # Calculate  steering value with Yaw Controller
        # rospy.loginfo("Current linear speed: %.2f, Target linear speed: %.2f", current_vel_lin_x, target_vel_lin_x)
        #rospy.loginfo("Current angular speed: %.4f, Target angular speed: %.4f", current_vel_ang_z, target_vel_ang_z)
        steering_yaw_controller = self.yaw_controller.get_steering(target_vel_lin_x, target_vel_ang_z, current_vel_lin_x)
        
        max_delta_target_vel_ang_z = 0.001
        if (target_vel_ang_z > (self.last_target_vel_ang_z + max_delta_target_vel_ang_z)):
            target_vel_ang_z = (self.last_target_vel_ang_z + max_delta_target_vel_ang_z)
        elif (target_vel_ang_z < (self.last_target_vel_ang_z - max_delta_target_vel_ang_z)):
            target_vel_ang_z = (self.last_target_vel_ang_z - max_delta_target_vel_ang_z)
        self.last_target_vel_ang_z = target_vel_ang_z
        
        #rospy.loginfo("Corrected target angular speed: %.4f", target_vel_ang_z)
        
        ang_z_vel_error = target_vel_ang_z - current_vel_ang_z
        #rospy.loginfo("ang_z_vel_error: %.2f, target_vel_ang_z: %.2f, current_vel_ang_z: %.2f", ang_z_vel_error, target_vel_ang_z, current_vel_ang_z)
        steering_pid_controller = self.steering_controller.step(ang_z_vel_error, delta_t)

        steering = (1.0 + abs(steering_pid_controller))*steering_yaw_controller
        
        # This avoids strong oscillations on the steering angle
        steering_max_delta = 0.1
        if steering > (self.last_steering + steering_max_delta):
            steering = self.last_steering + steering_max_delta
        elif steering < (self.last_steering - steering_max_delta):
            steering = self.last_steering - steering_max_delta
        self.last_steering = steering
        
        if steering > self.max_total_steering:
            steering = self.max_total_steering
        elif steering < -self.max_total_steering:
            steering = -self.max_total_steering
        
        # steering = steering_yaw_controller  As it was before
        #rospy.loginfo("Steering yaw controller: %.2f, steering pid controller: %.2f, total steering: %.2f", steering_yaw_controller, steering_pid_controller, steering)

        #rospy.loginfo("Control function finished")
        return throttle, brake_torque, steering
