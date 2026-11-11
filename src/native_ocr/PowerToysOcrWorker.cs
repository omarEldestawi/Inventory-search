// PowerToysOcrWorker.cs
// Standalone Native Windows OCR Worker (PowerToys Architecture + Dual-Language ar-SA / en-US)
// Compiles natively on any Windows 10/11 machine via built-in csc.exe or dotnet publish.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Windows.Foundation;
using Windows.Globalization;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Security.Cryptography;
using Windows.Storage.Streams;

namespace NativeOcr
{
    internal sealed class OcrRequest
    {
        public string ImagePath { get; set; }
        public string ImageBase64 { get; set; }
        public bool? Upscale { get; set; }
        public int? Padding { get; set; }
        public string Command { get; set; }
    }

    internal sealed class OcrWordDto
    {
        public string Text { get; set; }
        public double[] Bbox { get; set; }
        public string Lang { get; set; }

        public OcrWordDto()
        {
            Text = string.Empty;
            Bbox = new double[0];
            Lang = string.Empty;
        }

        public double X0 { get { return Bbox[0]; } }
        public double Y0 { get { return Bbox[1]; } }
        public double X1 { get { return Bbox[2]; } }
        public double Y1 { get { return Bbox[3]; } }
        public double Width { get { return Math.Max(0.0, X1 - X0); } }
        public double Height { get { return Math.Max(0.0, Y1 - Y0); } }
        public double MidX { get { return (X0 + X1) * 0.5; } }
        public double MidY { get { return (Y0 + Y1) * 0.5; } }
    }

    internal sealed class OcrLineDto
    {
        public string Text { get; set; }
        public double[] Bbox { get; set; }
        public List<OcrWordDto> Words { get; set; }

        public OcrLineDto()
        {
            Text = string.Empty;
            Bbox = new double[0];
            Words = new List<OcrWordDto>();
        }
    }

    internal sealed class OcrResponse
    {
        public string Status { get; set; }
        public List<OcrLineDto> Lines { get; set; }
        public string Error { get; set; }

        public OcrResponse()
        {
            Status = "ok";
            Lines = new List<OcrLineDto>();
        }
    }

    internal static class Program
    {
        private static readonly Regex PureAsciiTokenRegex = new Regex(
            @"^[A-Za-z0-9]+([.,%/+\-:][A-Za-z0-9%]*)*%?$",
            RegexOptions.Compiled | RegexOptions.CultureInvariant
        );

        private static readonly JavaScriptSerializer JsonSerializerInstance = new JavaScriptSerializer
        {
            MaxJsonLength = int.MaxValue
        };

        public static int Main(string[] args)
        {
            return MainAsync().GetAwaiter().GetResult();
        }

        private static async Task<int> MainAsync()
        {
            Console.InputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            Console.OutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

            OcrEngine arEngine = TryCreateEngine("ar-SA") ?? TryCreateEngine("ar");
            OcrEngine enEngine = TryCreateEngine("en-US") ?? TryCreateEngine("en");

            if (arEngine == null && enEngine == null)
            {
                enEngine = OcrEngine.TryCreateFromUserProfileLanguages();
            }

            // Emit startup readiness token on Line 1 of stdout
            Console.Out.WriteLine("__READY__");
            await Console.Out.FlushAsync();

            string line;
            while ((line = await Console.In.ReadLineAsync()) != null)
            {
                string trimmed = line.Trim();
                if (string.IsNullOrEmpty(trimmed))
                {
                    continue;
                }

                OcrResponse response;
                string requestId = null;
                try
                {
                    OcrRequest request = ParseRequest(trimmed, out requestId);
                    if (request == null)
                    {
                        response = new OcrResponse { Status = "error", Error = "Null JSON request." };
                    }
                    else if (string.Equals(request.Command, "exit", StringComparison.OrdinalIgnoreCase) ||
                             string.Equals(request.Command, "quit", StringComparison.OrdinalIgnoreCase))
                    {
                        break;
                    }
                    else
                    {
                        response = await ProcessImageRequestAsync(request, arEngine, enEngine);
                    }
                }
                catch (Exception ex)
                {
                    response = new OcrResponse
                    {
                        Status = "error",
                        Error = ex.Message,
                        Lines = new List<OcrLineDto>()
                    };
                }

                string jsonOut = SerializeResponse(response, requestId);
                Console.Out.WriteLine(jsonOut);
                await Console.Out.FlushAsync();
            }

            return 0;
        }

        private static OcrRequest ParseRequest(string json, out string requestId)
        {
            requestId = null;
            var dict = JsonSerializerInstance.Deserialize<Dictionary<string, object>>(json);
            if (dict == null)
            {
                return null;
            }

            var req = new OcrRequest();
            object val;
            if (dict.TryGetValue("request_id", out val) && val != null)
                requestId = val.ToString();
            if (dict.TryGetValue("image_path", out val) && val != null)
                req.ImagePath = val.ToString();
            else if (dict.TryGetValue("ImagePath", out val) && val != null)
                req.ImagePath = val.ToString();

            if (dict.TryGetValue("image_base64", out val) && val != null)
                req.ImageBase64 = val.ToString();
            else if (dict.TryGetValue("ImageBase64", out val) && val != null)
                req.ImageBase64 = val.ToString();

            if (dict.TryGetValue("command", out val) && val != null)
                req.Command = val.ToString();
            else if (dict.TryGetValue("Command", out val) && val != null)
                req.Command = val.ToString();

            if (dict.TryGetValue("upscale", out val) && val != null)
                req.Upscale = Convert.ToBoolean(val);
            else if (dict.TryGetValue("Upscale", out val) && val != null)
                req.Upscale = Convert.ToBoolean(val);

            if (dict.TryGetValue("padding", out val) && val != null)
                req.Padding = Convert.ToInt32(val);
            else if (dict.TryGetValue("Padding", out val) && val != null)
                req.Padding = Convert.ToInt32(val);

            return req;
        }

        private static string SerializeResponse(OcrResponse resp, string requestId)
        {
            var linesList = new List<Dictionary<string, object>>(resp.Lines.Count);
            foreach (var l in resp.Lines)
            {
                var wordsList = new List<Dictionary<string, object>>(l.Words.Count);
                foreach (var w in l.Words)
                {
                    wordsList.Add(new Dictionary<string, object>
                    {
                        { "text", w.Text },
                        { "bbox", w.Bbox },
                        { "lang", w.Lang }
                    });
                }
                linesList.Add(new Dictionary<string, object>
                {
                    { "text", l.Text },
                    { "bbox", l.Bbox },
                    { "words", wordsList }
                });
            }

            var root = new Dictionary<string, object>
            {
                { "status", resp.Status },
                { "request_id", requestId },
                { "lines", linesList }
            };
            if (!string.IsNullOrEmpty(resp.Error))
            {
                root["error"] = resp.Error;
            }
            return JsonSerializerInstance.Serialize(root);
        }

        private static OcrEngine TryCreateEngine(string languageTag)
        {
            try
            {
                if (!Language.IsWellFormed(languageTag))
                {
                    return null;
                }
                Language lang = new Language(languageTag);
                if (!OcrEngine.IsLanguageSupported(lang))
                {
                    return null;
                }
                return OcrEngine.TryCreateFromLanguage(lang);
            }
            catch
            {
                return null;
            }
        }

        private static Task<T> AwaitWinRtAsync<T>(IAsyncOperation<T> op)
        {
            var tcs = new TaskCompletionSource<T>();
            op.Completed = (info, status) =>
            {
                try
                {
                    if (status == AsyncStatus.Completed)
                    {
                        tcs.TrySetResult(info.GetResults());
                    }
                    else if (status == AsyncStatus.Error)
                    {
                        tcs.TrySetException(info.ErrorCode ?? new Exception("WinRT async error."));
                    }
                    else
                    {
                        tcs.TrySetCanceled();
                    }
                }
                catch (Exception ex)
                {
                    tcs.TrySetException(ex);
                }
            };
            return tcs.Task;
        }

        private static async Task<OcrResponse> ProcessImageRequestAsync(
            OcrRequest request,
            OcrEngine arEngine,
            OcrEngine enEngine)
        {
            using (Bitmap srcBitmap = LoadInputBitmap(request))
            {
                int origW = srcBitmap.Width;
                int origH = srcBitmap.Height;

                if (origW <= 0 || origH <= 0)
                {
                    return new OcrResponse { Status = "error", Error = "Invalid image dimensions." };
                }

                // PowerToys Image Preprocessing:
                // 1. If request.Upscale is explicitly true (and origH < 1000), or if unspecified and origH < 400,
                //    upscale by 2.0x using HighQualityBicubic interpolation.
                // 2. Add a 16-pixel solid white (#FFFFFF) border on all 4 sides.
                bool shouldUpscale = request.Upscale.HasValue
                    ? (request.Upscale.Value && origH < 1000)
                    : (origH < 400);
                double scale = shouldUpscale ? 2.0 : 1.0;
                int pad = Math.Max(0, request.Padding ?? 16);

                int scaledW = Math.Max(1, (int)Math.Round(origW * scale));
                int scaledH = Math.Max(1, (int)Math.Round(origH * scale));
                int canvasW = scaledW + (2 * pad);
                int canvasH = scaledH + (2 * pad);

                using (Bitmap preprocessedBitmap = new Bitmap(canvasW, canvasH, PixelFormat.Format32bppPArgb))
                {
                    using (Graphics g = Graphics.FromImage(preprocessedBitmap))
                    {
                        g.Clear(Color.White);
                        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                        g.SmoothingMode = SmoothingMode.HighQuality;
                        g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                        g.CompositingQuality = CompositingQuality.HighQuality;

                        g.DrawImage(
                            srcBitmap,
                            new Rectangle(pad, pad, scaledW, scaledH),
                            new Rectangle(0, 0, origW, origH),
                            GraphicsUnit.Pixel
                        );
                    }

                    using (SoftwareBitmap softwareBitmap = ConvertToSoftwareBitmap(preprocessedBitmap))
                    {
                        Task<OcrResult> arTask = arEngine != null
                            ? AwaitWinRtAsync(arEngine.RecognizeAsync(softwareBitmap))
                            : Task.FromResult<OcrResult>(null);

                        Task<OcrResult> enTask = enEngine != null
                            ? AwaitWinRtAsync(enEngine.RecognizeAsync(softwareBitmap))
                            : Task.FromResult<OcrResult>(null);

                        await Task.WhenAll(arTask, enTask);

                        OcrResult arResult = await arTask;
                        OcrResult enResult = await enTask;

                        List<OcrWordDto> arWords = ExtractWords(arResult, "ar-SA", pad, scale, origW, origH);
                        List<OcrWordDto> enWords = ExtractWords(enResult, "en-US", pad, scale, origW, origH);

                        List<OcrWordDto> mergedWords = MergeDualLanguageWords(arWords, enWords);
                        List<OcrLineDto> lines = ReconstructLinesAndBiDiOrder(mergedWords);

                        return new OcrResponse
                        {
                            Status = "ok",
                            Lines = lines
                        };
                    }
                }
            }
        }

        private static Bitmap LoadInputBitmap(OcrRequest request)
        {
            if (!string.IsNullOrWhiteSpace(request.ImagePath))
            {
                if (!File.Exists(request.ImagePath))
                {
                    throw new FileNotFoundException("Image file not found: " + request.ImagePath);
                }
                using (FileStream fs = new FileStream(request.ImagePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (Image img = Image.FromStream(fs, useEmbeddedColorManagement: false, validateImageData: false))
                {
                    return new Bitmap(img);
                }
            }

            if (!string.IsNullOrWhiteSpace(request.ImageBase64))
            {
                byte[] bytes = Convert.FromBase64String(request.ImageBase64);
                using (MemoryStream ms = new MemoryStream(bytes))
                using (Image img = Image.FromStream(ms, useEmbeddedColorManagement: false, validateImageData: false))
                {
                    return new Bitmap(img);
                }
            }

            throw new ArgumentException("Either 'image_path' or 'image_base64' must be provided.");
        }

        private static SoftwareBitmap ConvertToSoftwareBitmap(Bitmap bmp)
        {
            int width = bmp.Width;
            int height = bmp.Height;
            Rectangle rect = new Rectangle(0, 0, width, height);
            BitmapData bmpData = bmp.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb);
            try
            {
                int rowBytes = width * 4;
                byte[] pixelBytes = new byte[rowBytes * height];
                IntPtr scan0 = bmpData.Scan0;
                int stride = bmpData.Stride;

                if (stride == rowBytes)
                {
                    Marshal.Copy(scan0, pixelBytes, 0, pixelBytes.Length);
                }
                else
                {
                    for (int y = 0; y < height; y++)
                    {
                        IntPtr rowPtr = IntPtr.Add(scan0, y * stride);
                        Marshal.Copy(rowPtr, pixelBytes, y * rowBytes, rowBytes);
                    }
                }

                IBuffer buffer = CryptographicBuffer.CreateFromByteArray(pixelBytes);
                return SoftwareBitmap.CreateCopyFromBuffer(
                    buffer,
                    BitmapPixelFormat.Bgra8,
                    width,
                    height,
                    BitmapAlphaMode.Premultiplied
                );
            }
            finally
            {
                bmp.UnlockBits(bmpData);
            }
        }

        private static double ClampVal(double val, double min, double max)
        {
            if (val < min) return min;
            if (val > max) return max;
            return val;
        }

        private static List<OcrWordDto> ExtractWords(
            OcrResult result,
            string langTag,
            int pad,
            double scale,
            int origW,
            int origH)
        {
            List<OcrWordDto> words = new List<OcrWordDto>();
            if (result == null || result.Lines == null)
            {
                return words;
            }

            foreach (OcrLine line in result.Lines)
            {
                foreach (OcrWord word in line.Words)
                {
                    string normalizedText = NormalizeNumeralsAndText(word.Text);
                    if (string.IsNullOrWhiteSpace(normalizedText))
                    {
                        continue;
                    }

                    var rect = word.BoundingRect;
                    double x0 = Math.Round(ClampVal((rect.X - pad) / scale, 0.0, origW), 2);
                    double y0 = Math.Round(ClampVal((rect.Y - pad) / scale, 0.0, origH), 2);
                    double x1 = Math.Round(ClampVal((rect.X + rect.Width - pad) / scale, 0.0, origW), 2);
                    double y1 = Math.Round(ClampVal((rect.Y + rect.Height - pad) / scale, 0.0, origH), 2);

                    if (x1 <= x0 || y1 <= y0)
                    {
                        continue;
                    }

                    words.Add(new OcrWordDto
                    {
                        Text = normalizedText,
                        Bbox = new double[] { x0, y0, x1, y1 },
                        Lang = langTag
                    });
                }
            }

            return words;
        }

        public static string NormalizeNumeralsAndText(string input)
        {
            if (string.IsNullOrEmpty(input))
            {
                return string.Empty;
            }

            StringBuilder sb = new StringBuilder(input.Length);
            foreach (char c in input)
            {
                if (c >= '\u0660' && c <= '\u0669')
                {
                    sb.Append((char)('0' + (c - '\u0660')));
                }
                else if (c >= '\u06F0' && c <= '\u06F9')
                {
                    sb.Append((char)('0' + (c - '\u06F0')));
                }
                else if (c == '\u066B')
                {
                    sb.Append('.');
                }
                else if (c == '\u066A')
                {
                    sb.Append('%');
                }
                else
                {
                    sb.Append(c);
                }
            }

            return sb.ToString().Trim();
        }

        private static bool IsPureAsciiToken(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return false;
            }
            foreach (char c in text)
            {
                if (c > 0x7F)
                {
                    return false;
                }
            }
            return PureAsciiTokenRegex.IsMatch(text);
        }

        private static bool ContainsAsciiDigit(string text)
        {
            foreach (char c in text)
            {
                if (c >= '0' && c <= '9')
                {
                    return true;
                }
            }
            return false;
        }

        private static bool ContainsArabicChar(string text)
        {
            foreach (char c in text)
            {
                if ((c >= '\u0600' && c <= '\u06FF') ||
                    (c >= '\u0750' && c <= '\u077F') ||
                    (c >= '\uFB50' && c <= '\uFDFF') ||
                    (c >= '\uFE70' && c <= '\uFEFF'))
                {
                    return true;
                }
            }
            return false;
        }

        private static int CountArabicLetters(string text)
        {
            int count = 0;
            foreach (char c in text)
            {
                if ((c >= '\u0621' && c <= '\u064A') || (c >= '\uFE70' && c <= '\uFEFC'))
                {
                    count++;
                }
            }
            return count;
        }

        private static bool BoxesOverlap(OcrWordDto a, OcrWordDto b)
        {
            double interY0 = Math.Max(a.Y0, b.Y0);
            double interY1 = Math.Min(a.Y1, b.Y1);
            double interH = Math.Max(0.0, interY1 - interY0);
            double minH = Math.Max(1.0, Math.Min(a.Height, b.Height));
            if (interH / minH < 0.35)
            {
                return false;
            }

            double interX0 = Math.Max(a.X0, b.X0);
            double interX1 = Math.Min(a.X1, b.X1);
            double interW = Math.Max(0.0, interX1 - interX0);
            double minW = Math.Max(1.0, Math.Min(a.Width, b.Width));
            return (interW / minW) >= 0.30;
        }

        private static List<OcrWordDto> MergeDualLanguageWords(
            List<OcrWordDto> arWords,
            List<OcrWordDto> enWords)
        {
            if (arWords.Count == 0)
            {
                return enWords;
            }
            if (enWords.Count == 0)
            {
                return arWords;
            }

            List<OcrWordDto> acceptedEnWords = new List<OcrWordDto>();
            HashSet<int> replacedArIndices = new HashSet<int>();

            foreach (OcrWordDto enWord in enWords)
            {
                if (!IsPureAsciiToken(enWord.Text))
                {
                    continue;
                }

                List<int> overlappingAr = new List<int>();
                for (int i = 0; i < arWords.Count; i++)
                {
                    if (BoxesOverlap(enWord, arWords[i]))
                    {
                        overlappingAr.Add(i);
                    }
                }

                bool hasDigit = ContainsAsciiDigit(enWord.Text);
                bool preferEn = false;

                if (overlappingAr.Count == 0)
                {
                    preferEn = hasDigit || enWord.Text.Length >= 2;
                }
                else
                {
                    double totalArWidth = overlappingAr.Sum(idx => arWords[idx].Width);
                    int maxArabicLetters = overlappingAr.Max(idx => CountArabicLetters(arWords[idx].Text));

                    if (hasDigit)
                    {
                        bool isSingleStrokeNoiseOnWideArabic =
                            (enWord.Text == "1" || enWord.Text == "11") &&
                            maxArabicLetters >= 3 &&
                            enWord.Width < 0.45 * totalArWidth;

                        preferEn = !isSingleStrokeNoiseOnWideArabic;
                    }
                    else
                    {
                        bool isShortVerticalStrokeNoise =
                            enWord.Text.All(c => c == 'l' || c == 'I' || c == 'i' || c == 'j') &&
                            maxArabicLetters >= 2;

                        if (!isShortVerticalStrokeNoise && maxArabicLetters < 2)
                        {
                            preferEn = true;
                        }
                    }
                }

                if (preferEn)
                {
                    acceptedEnWords.Add(enWord);
                    foreach (int idx in overlappingAr)
                    {
                        replacedArIndices.Add(idx);
                    }
                }
            }

            List<OcrWordDto> merged = new List<OcrWordDto>();
            for (int i = 0; i < arWords.Count; i++)
            {
                if (!replacedArIndices.Contains(i))
                {
                    merged.Add(arWords[i]);
                }
            }
            merged.AddRange(acceptedEnWords);

            return merged;
        }

        private static List<OcrLineDto> ReconstructLinesAndBiDiOrder(List<OcrWordDto> words)
        {
            List<OcrLineDto> resultLines = new List<OcrLineDto>();
            if (words.Count == 0)
            {
                return resultLines;
            }

            List<OcrWordDto> sortedByY = words.OrderBy(w => w.MidY).ThenBy(w => w.X0).ToList();
            List<List<OcrWordDto>> lineClusters = new List<List<OcrWordDto>>();

            foreach (OcrWordDto word in sortedByY)
            {
                List<OcrWordDto> bestCluster = null;
                double bestDiff = double.MaxValue;

                foreach (List<OcrWordDto> cluster in lineClusters)
                {
                    double clusterMidY = cluster.Average(w => w.MidY);
                    double clusterAvgH = Math.Max(8.0, cluster.Average(w => w.Height));
                    double diff = Math.Abs(word.MidY - clusterMidY);

                    double minY0 = cluster.Min(w => w.Y0);
                    double maxY1 = cluster.Max(w => w.Y1);
                    double interH = Math.Max(0.0, Math.Min(word.Y1, maxY1) - Math.Max(word.Y0, minY0));
                    double minH = Math.Max(1.0, Math.Min(word.Height, maxY1 - minY0));

                    if ((diff <= 0.55 * clusterAvgH || (interH / minH) >= 0.45) && diff < bestDiff)
                    {
                        bestDiff = diff;
                        bestCluster = cluster;
                    }
                }

                if (bestCluster != null)
                {
                    bestCluster.Add(word);
                }
                else
                {
                    lineClusters.Add(new List<OcrWordDto> { word });
                }
            }

            foreach (List<OcrWordDto> cluster in lineClusters.OrderBy(c => c.Average(w => w.MidY)))
            {
                List<OcrWordDto> orderedWords = SortWordsBiDi(cluster);
                double lx0 = Math.Round(orderedWords.Min(w => w.X0), 2);
                double ly0 = Math.Round(orderedWords.Min(w => w.Y0), 2);
                double lx1 = Math.Round(orderedWords.Max(w => w.X1), 2);
                double ly1 = Math.Round(orderedWords.Max(w => w.Y1), 2);

                resultLines.Add(new OcrLineDto
                {
                    Text = string.Join(" ", orderedWords.Select(w => w.Text)),
                    Bbox = new double[] { lx0, ly0, lx1, ly1 },
                    Words = orderedWords
                });
            }

            return resultLines;
        }

        private static List<OcrWordDto> SortWordsBiDi(List<OcrWordDto> lineWords)
        {
            bool hasArabic = lineWords.Any(w => ContainsArabicChar(w.Text));
            if (!hasArabic)
            {
                return lineWords.OrderBy(w => w.MidX).ToList();
            }

            List<OcrWordDto> rtlSorted = lineWords.OrderByDescending(w => w.MidX).ToList();
            double avgH = Math.Max(10.0, rtlSorted.Average(w => w.Height));

            int i = 0;
            while (i < rtlSorted.Count)
            {
                if (ContainsArabicChar(rtlSorted[i].Text))
                {
                    i++;
                    continue;
                }

                int j = i;
                while (j + 1 < rtlSorted.Count &&
                       !ContainsArabicChar(rtlSorted[j + 1].Text))
                {
                    double gap = Math.Max(0.0, rtlSorted[j].X0 - rtlSorted[j + 1].X1);
                    if (gap <= 1.0 * avgH)
                    {
                        j++;
                    }
                    else
                    {
                        break;
                    }
                }

                if (j > i)
                {
                    rtlSorted.Reverse(i, j - i + 1);
                }
                i = j + 1;
            }

            return rtlSorted;
        }
    }
}
