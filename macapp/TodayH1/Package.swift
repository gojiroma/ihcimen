// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "TodayH1",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "TodayH1",
            path: "Sources/TodayH1"
        )
    ]
)
