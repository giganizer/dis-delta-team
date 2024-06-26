cmake_minimum_required(VERSION 3.8)
project(delta_interfaces)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/LevelObjects.msg"
  "msg/GreeterJob.msg"
  "msg/ExplorerJob.msg"
  "msg/JobStatus.msg"
  "msg/RingObjects.msg"
  "msg/CylinderObjects.msg"
  "msg/SayText.msg"
  "msg/ParkingJob.msg"
  "msg/MonalisaJob.msg"
  "srv/Empty.srv"
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
