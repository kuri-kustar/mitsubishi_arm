import roslib, time
import rosparam
import rospy, sys
import os.path
import yaml
from controller_manager_msgs.srv import *
from std_msgs.msg import *
import argparse

loaded = []

# Declare these here so they can be shared between functions
load_controller_service = ""
switch_controller_service = ""
unload_controller_service = ""


def shutdown():
    global loaded,unload_controller_service,load_controller_service,switch_controller_service

    try:
        # unloader
        unload_controller = rospy.ServiceProxy(unload_controller_service, UnloadController)

        # switcher
        switch_controller = rospy.ServiceProxy(switch_controller_service, SwitchController)

        switch_controller([], loaded, SwitchControllerRequest.STRICT)
        for name in reversed(loaded):
            rospy.logout("Trying to unload %s" % name)
            unload_controller(name)
            rospy.logout("Succeeded in unloading %s" % name)
    except (rospy.ServiceException, rospy.exceptions.ROSException) as exc:
        rospy.logwarn("Controller Spawner couldn't reach controller_manager to take down controllers.")

def parse_args(args=None):
    parser = argparse.ArgumentParser(description='Controller spawner')
    parser.add_argument('--stopped', action='store_true',
                        help='loads controllers, but does not start them')
    parser.add_argument('--wait-for', metavar='topic', help='does not load or '
                        'start controllers until it hears "True" on a topic (Bool)')
    parser.add_argument('--namespace', metavar='ns',
                        help='namespace of the controller_manager services')
    parser.add_argument('--timeout', metavar='T', type=int, default=30,
                        help='how long to wait for controller_manager services [s] (default: 30)')
    parser.add_argument('controllers', metavar='controller', nargs='+',
                        help='controllers to load')
    return parser.parse_args(args=args)

def main():
    global unload_controller_service,load_controller_service,switch_controller_service

    args = parse_args(rospy.myargv()[1:])

    wait_for_topic = args.wait_for
    autostart = 1 if not args.stopped else 0
    robot_namespace = args.namespace or ""
    timeout = args.timeout

    rospy.init_node('spawner', anonymous=True)

    # add a '/' to the namespace if needed
    if robot_namespace and robot_namespace[-1] != '/':
        robot_namespace = robot_namespace+'/'

    # set service names based on namespace
    load_controller_service = robot_namespace+"controller_manager/load_controller"
    unload_controller_service = robot_namespace+"controller_manager/unload_controller"
    switch_controller_service = robot_namespace+"controller_manager/switch_controller"

    try:
        # loader
        rospy.loginfo("Controller Spawner: Waiting for service "+load_controller_service)
        rospy.wait_for_service(load_controller_service, timeout=timeout)
        load_controller = rospy.ServiceProxy(load_controller_service, LoadController)

        # switcher
        rospy.loginfo("Controller Spawner: Waiting for service "+switch_controller_service)
        rospy.wait_for_service(switch_controller_service, timeout=timeout)
        switch_controller = rospy.ServiceProxy(switch_controller_service, SwitchController)

        # unloader
        # NOTE: We check for the unloader's existence here, although its used on shutdown because shutdown
        # should be fast. Further, we're interested in knowing if we have a compliant controller manager from
        # early on
        rospy.loginfo("Controller Spawner: Waiting for service "+unload_controller_service)
        rospy.wait_for_service(unload_controller_service, timeout=timeout)

    except rospy.exceptions.ROSException:
        rospy.logwarn("Controller Spawner couldn't find the expected controller_manager ROS interface.")
        return

    if wait_for_topic:
        # This has to be a list since Python has a peculiar mecanism to determine
        # whether a variable is local to a function or not:
        # if the variable is assigned in the body of the function, then it is
        # assumed to be local. Modifying a mutable object (like a list)
        # works around this debatable "design choice".
        wait_for_topic_result = [None]

        def wait_for_topic_cb(msg):
            wait_for_topic_result[0] = msg
            rospy.logdebug("Heard from wait-for topic: %s" % str(msg.data))
        rospy.Subscriber(wait_for_topic, Bool, wait_for_topic_cb)
        started_waiting = time.time()

        # We might not have receieved any time messages yet
        warned_about_not_hearing_anything = False
        while not wait_for_topic_result[0]:
            time.sleep(0.01)
            if rospy.is_shutdown():
                return
            if not warned_about_not_hearing_anything:
                if time.time() - started_waiting > timeout:
                    warned_about_not_hearing_anything = True
                    rospy.logwarn("Controller Spawner hasn't heard anything from its \"wait for\" topic (%s)" % \
                                      wait_for_topic)
        while not wait_for_topic_result[0].data:
            time.sleep(0.01)
            if rospy.is_shutdown():
                return

    # hook for unloading controllers on shutdown
    rospy.on_shutdown(shutdown)

    # find yaml files to load
    controllers = []
    for name in args.controllers:
        if os.path.exists(name):
            # load yaml file onto the parameter server, using the namespace specified in the yaml file
            rosparam.set_param("",open(name))
            # list the controllers to be loaded
            name_yaml = yaml.load(open(name))
            for controller in name_yaml:
                controllers.append(controller)
        else:
            controllers.append(name)

    # load controllers
    for name in controllers:
        rospy.loginfo("Loading controller: "+name)
        resp = load_controller(name)
        if resp.ok != 0:
            loaded.append(name)
        else:
            time.sleep(1) # give error message a chance to get out
            rospy.logerr("Failed to load %s" % name)

    rospy.loginfo("Controller Spawner: Loaded controllers: %s" % ', '.join(loaded))

    if rospy.is_shutdown():
        return

    # start controllers is requested
    if autostart:
        resp = switch_controller(loaded, [], 2)
        if resp.ok != 0:
            rospy.loginfo("Started controllers: %s" % ', '.join(loaded))
        else:
            rospy.logerr("Failed to start controllers: %s" % ', '.join(loaded))

    rospy.spin()

if __name__ == '__main__': main()
