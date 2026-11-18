using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Orchard;

namespace Orchard.Tests
{
    // End-to-end smoke test: the game must boot from an empty scene through OrchardBoot,
    // build the real map, create the real cameras, start night one and spawn the first wave.
    // Any exception or error log in the player loop fails this test automatically.
    public class GameplaySmokeTests
    {
        [UnityTest]
        [Timeout(120000)]
        public IEnumerator BootsFromAnEmptyScene_AndPlaysTheFirstNight()
        {
            // Awake runs when OrchardBoot adds the component after the scene loads; Start runs
            // on the next frame. Two frames are enough for both.
            yield return null;
            yield return null;

            OrchardGame game = OrchardGame.I;
            Assert.IsNotNull(game, "OrchardBoot did not create the game from an empty scene");
            Assert.IsTrue(game.staticBuilt, "the procedural map was not built");
            Assert.AreEqual(6, game.trees.Count);
            Assert.IsNotNull(game.farmer);
            Assert.IsNotNull(game.pip);
            Assert.IsNotNull(game.thistle);
            Assert.IsFalse(game.running, "the title card must be showing before the player starts");
            Assert.AreEqual(0, game.enemies.Count);

            OrchardGame[] games = Object.FindObjectsByType<OrchardGame>(FindObjectsSortMode.None);
            Assert.AreEqual(1, games.Length, "the boot hook must not create a second game");

            Camera board = null;
            Camera screen = null;
            foreach (Camera c in Camera.allCameras)
            {
                if (c.name == "Orchard Board Camera") board = c;
                else if (c.name == "Orchard Screen Camera") screen = c;
            }
            Assert.IsNotNull(board, "the board camera was not created");
            Assert.IsNotNull(screen, "the screen-clearing camera was not created");
            Assert.IsTrue(board.orthographic, "the board must be rendered by an orthographic camera");
            Assert.AreEqual(Quaternion.identity, board.transform.rotation, "the board camera must look straight down");
            Assert.AreEqual(352f, board.orthographicSize, 0.01f, "the board camera must show the full 16-row board");
            Assert.AreEqual(new Vector3(528f, -352f, -10f), board.transform.position);
            Assert.IsNotNull(board.targetTexture, "the board camera must render into the UI texture");

            game.StartClicked();

            Assert.IsTrue(game.running);
            Assert.AreEqual(1, game.night);
            Assert.AreEqual(5, CountYellow(game), "night one starts with five scatterlings");
            Assert.AreEqual(7, game.spawnQueue.Count, "5 shamblers + 1 stalker + 1 black-bird flock");

            float start = Time.realtimeSinceStartup;
            while (Time.realtimeSinceStartup - start < 1.5f) yield return null;
            Assert.Greater(game.nightTime, 0.5, "the night clock must advance");

            float deadline = Time.realtimeSinceStartup + 10f;
            while (Time.realtimeSinceStartup < deadline && game.enemies.Count <= 5) yield return null;

            Assert.Greater(game.enemies.Count, 5, "the first wave must spawn into the orchard");
            Assert.AreEqual(1, game.night, "the first night must still be running");
            Assert.IsFalse(game.gameOver);
            Assert.IsNotNull(Object.FindAnyObjectByType<OrchardGame>());
        }

        static int CountYellow(OrchardGame game)
        {
            int n = 0;
            foreach (Enemy e in game.enemies) if (e.type == "scatterling") n++;
            return n;
        }
    }
}
