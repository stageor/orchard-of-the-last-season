#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Orchard.CI
{
    // Build entry points used by GameCI and by local release engineers.
    //
    //   Unity -batchmode -quit -projectPath . -executeMethod Orchard.CI.OrchardBuild.BuildWindows
    //   Unity -batchmode -quit -projectPath . -executeMethod Orchard.CI.OrchardBuild.BuildWebGL
    //
    // The project deliberately has no hand-wired scene. OrchardBoot creates the game from any
    // scene, but a player still needs one scene in the build, so this script makes sure a minimal
    // empty Bootstrap scene exists and is the enabled build scene. It never overwrites an existing
    // scene and never changes the project's Unity version.
    public static class OrchardBuild
    {
        public const string BootstrapScenePath = "Assets/Orchard/Scenes/Bootstrap.unity";
        public const string WindowsOutput = "Build/Windows/OrchardOfTheLastSeason.exe";
        public const string WebGLOutput = "Build/WebGL";

        [MenuItem("Orchard/CI/Build Windows x64")]
        public static void BuildWindows()
        {
            Build(BuildTarget.StandaloneWindows64, WindowsOutput);
        }

        [MenuItem("Orchard/CI/Build WebGL")]
        public static void BuildWebGL()
        {
            Build(BuildTarget.WebGL, WebGLOutput);
        }

        static void Build(BuildTarget target, string outputPath)
        {
            EnsureBootstrapScene();
            ConfigurePlayer(target);

            string[] scenes = EnabledScenes();
            if (scenes.Length == 0)
                throw new InvalidOperationException("No enabled scenes in EditorBuildSettings; refusing to build an empty player.");

            string outputDir = target == BuildTarget.WebGL ? outputPath : Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(outputDir)) Directory.CreateDirectory(outputDir);

            BuildPlayerOptions options = new BuildPlayerOptions();
            options.scenes = scenes;
            options.locationPathName = outputPath;
            options.target = target;
            options.options = BuildOptions.None;

            Debug.Log("[OrchardBuild] Unity " + Application.unityVersion + " -> " + target + " at " + outputPath);
            BuildReport report = BuildPipeline.BuildPlayer(options);
            BuildSummary summary = report.summary;

            if (summary.result != BuildResult.Succeeded)
            {
                throw new InvalidOperationException(
                    "Unity build failed for " + target + ": " + summary.result +
                    " (" + summary.totalErrors + " errors, " + summary.totalWarnings + " warnings)");
            }

            WriteBuildInfo(outputDir, target, summary);
            Debug.Log("[OrchardBuild] Build succeeded: " + outputPath + " (" + summary.totalSize + " bytes)");
        }

        static void ConfigurePlayer(BuildTarget target)
        {
            // WebGL must run from any static host with no Content-Encoding headers, which is the
            // project-wide contract. Refuse to silently produce a compressed build.
            if (target == BuildTarget.WebGL)
            {
                if (PlayerSettings.WebGL.compressionFormat != WebGLCompressionFormat.Disabled)
                {
                    Debug.LogWarning("[OrchardBuild] webGLCompressionFormat was not Disabled; forcing Disabled for this build. " +
                                     "ProjectSettings.asset should stay at webGLCompressionFormat: 2.");
                    PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
                }
                if (PlayerSettings.WebGL.decompressionFallback)
                {
                    PlayerSettings.WebGL.decompressionFallback = false;
                }
            }

            BuildTargetGroup group = BuildPipeline.GetBuildTargetGroup(target);
            if (EditorUserBuildSettings.activeBuildTarget != target)
            {
                if (!EditorUserBuildSettings.SwitchActiveBuildTarget(group, target))
                    throw new InvalidOperationException("Could not switch the active build target to " + target + ".");
            }
        }

        // If the repository is ever used without the committed Bootstrap scene, recreate the
        // smallest possible scene through the real editor API instead of hand-writing YAML.
        public static void EnsureBootstrapScene()
        {
            if (!File.Exists(BootstrapScenePath))
            {
                string dir = Path.GetDirectoryName(BootstrapScenePath);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
                EditorSceneManager.SaveScene(scene, BootstrapScenePath);
                AssetDatabase.Refresh();
                Debug.Log("[OrchardBuild] Created missing bootstrap scene at " + BootstrapScenePath);
            }

            List<EditorBuildSettingsScene> scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            bool found = false;
            for (int i = 0; i < scenes.Count; i++)
            {
                if (scenes[i].path == BootstrapScenePath)
                {
                    found = true;
                    if (!scenes[i].enabled)
                    {
                        scenes[i] = new EditorBuildSettingsScene(BootstrapScenePath, true);
                        EditorBuildSettings.scenes = scenes.ToArray();
                    }
                    break;
                }
            }
            if (!found)
            {
                scenes.Add(new EditorBuildSettingsScene(BootstrapScenePath, true));
                EditorBuildSettings.scenes = scenes.ToArray();
                Debug.Log("[OrchardBuild] Added bootstrap scene to EditorBuildSettings.");
            }
        }

        static string[] EnabledScenes()
        {
            List<string> scenes = new List<string>();
            foreach (EditorBuildSettingsScene scene in EditorBuildSettings.scenes)
                if (scene.enabled && !string.IsNullOrEmpty(scene.path)) scenes.Add(scene.path);
            return scenes.ToArray();
        }

        // Small machine-readable manifest that lets CI prove which source commit, editor version
        // and settings produced the player. Written into the artifact, never into git.
        static void WriteBuildInfo(string outputDir, BuildTarget target, BuildSummary summary)
        {
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("product=" + PlayerSettings.productName);
            sb.AppendLine("version=" + PlayerSettings.bundleVersion);
            sb.AppendLine("unityVersion=" + Application.unityVersion);
            sb.AppendLine("target=" + target);
            sb.AppendLine("commit=" + Env("GITHUB_SHA", "local"));
            sb.AppendLine("repository=" + Env("GITHUB_REPOSITORY", "local"));
            sb.AppendLine("workflowRun=" + Env("GITHUB_RUN_ID", "local"));
            sb.AppendLine("builtAtUtc=" + DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"));
            sb.AppendLine("sizeBytes=" + summary.totalSize);
            sb.AppendLine("totalErrors=" + summary.totalErrors);
            sb.AppendLine("totalWarnings=" + summary.totalWarnings);
            if (target == BuildTarget.WebGL)
                sb.AppendLine("webglCompression=" + PlayerSettings.WebGL.compressionFormat);

            string file = Path.Combine(outputDir, "BUILD_INFO.txt");
            File.WriteAllText(file, sb.ToString());
        }

        static string Env(string name, string fallback)
        {
            string v = Environment.GetEnvironmentVariable(name);
            return string.IsNullOrEmpty(v) ? fallback : v;
        }
    }
}
#endif
