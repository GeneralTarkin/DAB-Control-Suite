using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using DABControlCenter.Models;
using DABControlCenter.Services;

namespace DABControlCenter;

public partial class MainWindow : Window
{
    private readonly DabServerClient _client = new();
    private readonly DispatcherTimer _refreshTimer;
    private bool _requestInProgress;

    public MainWindow()
    {
        InitializeComponent();

        _refreshTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(5)
        };

        _refreshTimer.Tick += async (_, _) => await RefreshStatusAsync();
    }

    private async void ConnectButton_Click(object sender, RoutedEventArgs e)
    {
        _refreshTimer.Stop();
        await RefreshStatusAsync();

        if (ConnectionTextBlock.Text == "Connected")
        {
            _refreshTimer.Start();
        }
    }

    private async Task RefreshStatusAsync()
    {
        if (_requestInProgress)
        {
            return;
        }

        _requestInProgress = true;

        try
        {
            DabStatus status =
                await _client.GetStatusAsync(ServerAddressTextBox.Text);

            UpdateUi(status);
        }
        finally
        {
            _requestInProgress = false;
        }
    }

    private void UpdateUi(DabStatus status)
    {
        Brush success = (Brush)FindResource("SuccessBrush");
        Brush danger = (Brush)FindResource("DangerBrush");
        Brush muted = (Brush)FindResource("MutedTextBrush");

        if (!status.Connected)
        {
            ConnectionIndicator.Background = danger;
            ConnectionTextBlock.Text = "Disconnected";
            ConnectionTextBlock.Foreground = danger;
            LastUpdateTextBlock.Text =
                string.IsNullOrWhiteSpace(status.ErrorMessage)
                    ? "Connection failed"
                    : status.ErrorMessage;

            _refreshTimer.Stop();
            return;
        }

        ConnectionIndicator.Background = success;
        ConnectionTextBlock.Text = "Connected";
        ConnectionTextBlock.Foreground = success;

        StationNameTextBlock.Text = status.StationName;
        RadiotextTextBlock.Text = status.Radiotext;
        EnsembleTextBlock.Text = status.Ensemble;
        FrequencyTextBlock.Text = status.Frequency;

        RssiProgressBar.Value = Math.Clamp(status.Rssi, 0, 100);
        RssiTextBlock.Text = status.Rssi.ToString();

        SnrProgressBar.Value = Math.Clamp(status.Snr, 0, 30);
        SnrTextBlock.Text = status.Snr.ToString();

        FicProgressBar.Value = Math.Clamp(status.FicQuality, 0, 100);
        FicTextBlock.Text = $"{status.FicQuality} %";

        StreamStatusTextBlock.Text =
            status.StreamRunning ? "Online" : "Offline";

        StreamStatusTextBlock.Foreground =
            status.StreamRunning ? success : danger;

        LastUpdateTextBlock.Text =
            $"Last update: {DateTime.Now:HH:mm:ss}";
        LastUpdateTextBlock.Foreground = muted;
    }
}
