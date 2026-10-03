// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "WelcomeMac",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "WelcomeMac", targets: ["WelcomeMac"])],
    targets: [.executableTarget(name: "WelcomeMac")]
)
